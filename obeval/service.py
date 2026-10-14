"""Điều phối một ca onboarding: recording Drive → booking → STT (qua temp-transcript) → chấm → DB.

Apps Script gọi `register` một lần cho mỗi file. Phần còn lại chạy qua Cloud Tasks gọi `advance`
5 phút/lần cho tới khi STT xong (tối đa 3 giờ — giờ cao điểm STT 20h–22h trùng giờ có onboarding),
rồi chấm ngay trong lượt đó. Mọi phụ thuộc ngoài đi qua `Deps` để test bằng đồ giả.
"""
from __future__ import annotations

import hmac
import json
import re
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

from . import db, gcs, prompt, recording, report, transcript

POLL_DELAY_SEC = 300
MAX_ATTEMPTS = 36
STALE_AFTER = timedelta(minutes=30)
SCORING_RETRIES = 6  # lượt thử thêm cho lỗi tạm của model, ngoài ngân sách chờ STT
TRANSIENT_RE = re.compile(r"\b(429|503)\b|RESOURCE_EXHAUSTED|UNAVAILABLE|DEADLINE_EXCEEDED|timed out")


class TransientError(RuntimeError):
    """Lỗi tạm (mạng, 5xx, quota) — thử lại ở lượt sau."""


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class Deps:
    store: object
    request_transcript: Callable[[str, str], str]
    download: Callable[[str, Path], bool]
    enqueue: Callable[[str, int, int, int], None]
    evaluate: Callable[[Path, dict, Path], dict]
    publish: bool = False
    now: Callable[[], datetime] = field(default=_utcnow)


def token_ok(given: str | None, expected: str | None) -> bool:
    """So sánh hằng thời gian; bỏ khoảng trắng/xuống dòng hai đầu (secret tạo bằng echo hay dính xuống dòng ở cuối)."""
    expected = (expected or "").strip()
    return bool(expected) and hmac.compare_digest((given or "").strip().encode(), expected.encode())


def register(file: dict, deps: Deps) -> dict:
    name = file.get("name") or ""
    if not recording.is_onboarding(name):
        return {"status": "ignored", "reason": "not_onboarding"}
    parsed = recording.parse(name)
    if parsed is None:
        deps.store.record_unmatched(file, "unparsable_name")
        return {"status": "unmatched", "reason": "unparsable_name"}
    rows = deps.store.booking_candidates(parsed.student_code, parsed.recorded_at)
    booking = recording.pick_booking(rows, parsed.recorded_at)
    if booking is None:
        deps.store.record_unmatched(file, "no_booking")
        return {"status": "unmatched", "reason": "no_booking"}
    bid = booking["id"]
    ev = deps.store.evaluation(bid)
    same_file = bool(ev) and ev.get("recording_file_id") == file["id"]
    if same_file and ev["status"] in ("done", "insufficient"):
        return {"status": "already_done", "booking_id": bid}
    if same_file and ev["status"] == "processing" and deps.now() - ev["updated_at"] < STALE_AFTER:
        # enqueue lần trước có thể đã lỗi sau khi start(): gửi lại (Cloud Tasks bỏ qua nếu task trùng tên đã có)
        deps.enqueue(bid, ev["run_id"], ev.get("attempts") or 0, 0)
        return {"status": "in_progress", "booking_id": bid}
    if ev and not same_file and ev["status"] in ("done", "insufficient"):
        # booking đã có bản ghi được chấm: file khác KHÔNG chấm đè (bản hoàn tất đầu tiên thắng), để người quyết định
        deps.store.record_unmatched(file, "duplicate_recording")
        return {"status": "duplicate", "booking_id": bid}
    run_id = deps.store.start(booking, file)
    deps.enqueue(bid, run_id, 0, 0)
    return {"status": "queued", "booking_id": bid}


def advance(booking_id: str, run_id: int, attempt: int, deps: Deps) -> dict:
    ev = deps.store.evaluation(booking_id)
    if not ev or ev.get("run_id") != run_id or ev["status"] != "processing":
        return {"status": "stale"}
    try:
        state = deps.request_transcript(booking_id, ev["recording_url"])
    except TransientError:
        state = "processing"
    except Exception as exc:  # noqa: BLE001 — lỗi cố định (4xx): thử lại vô ích
        return _fail(booking_id, run_id, deps, "error", f"temp-transcript: {exc}")
    if state == "error":
        return _fail(booking_id, run_id, deps, "error", "STT báo lỗi khi chép lời")
    if state == "done":
        outcome = _score_safely(booking_id, ev, deps)
        if outcome is not None:
            return _finish(booking_id, run_id, attempt, deps, outcome)
    if attempt >= MAX_ATTEMPTS:  # đang ở cửa sổ chấm lại: ngân sách chờ STT đã hết, dùng ngân sách chấm lại
        return _wait(booking_id, run_id, attempt, deps, "Lỗi tạm khi lấy transcript, chấm lại quá số lần thử",
                     SCORING_LIMIT)
    return _wait(booking_id, run_id, attempt, deps, "STT chưa xong sau 3 giờ")


SCORING_LIMIT = MAX_ATTEMPTS + SCORING_RETRIES


# Lỗi tạm của client Google (GCS / auth): nhận theo tên + module, không import google.* vào service.py.
_GOOGLE_TRANSIENT = {"ServiceUnavailable", "TooManyRequests", "InternalServerError", "GatewayTimeout",
                     "DeadlineExceeded", "TransportError"}


def _is_transient(exc: Exception) -> bool:
    if isinstance(exc, (TransientError, OSError)):
        return True
    return any(c.__module__.startswith("google.") and c.__name__ in _GOOGLE_TRANSIENT for c in type(exc).__mro__)


def _score_safely(booking_id: str, ev: dict, deps: Deps):
    """Tải + chấm; KHÔNG chạm store (lỗi DB phải nổi lên để Cloud Tasks gửi lại).

    Trả None nếu file transcript chưa có; ngược lại (kind, payload) với kind ∈ done/insufficient/transient/error.
    """
    try:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "transcript.json"
            if not deps.download(gcs.transcript_uri(booking_id), path):
                return None
            return _score(booking_id, ev, path, Path(tmp) / "out", deps)
    except Exception as exc:  # noqa: BLE001 — lỗi lạ: kết thúc ca (không để Cloud Tasks lặp vô hạn); lỗi tạm: chấm lại
        kind = "transient" if _is_transient(exc) else "error"
        return kind, f"{type(exc).__name__}: {exc}"


def _score(booking_id: str, ev: dict, path: Path, out_root: Path, deps: Deps):
    try:
        tr = transcript.load(path)
    except ValueError:
        return "insufficient", "Transcript rỗng hoặc không đọc được"
    if tr.source_format != "stt_diarized":  # legacy-backlog / legacy-long / legacy-fallback: không có vai
        return "insufficient", "STT trả bản không chia người nói — không chấm"
    meta = {"case_id": booking_id, "transcript_source": "stt_diarized"}
    if ev.get("session_date"):
        meta["session_date"] = str(ev["session_date"])
    res = deps.evaluate(path, meta, out_root)
    if res["state"] != "done":
        err = str(res.get("error") or "")
        return ("transient" if TRANSIENT_RE.search(err) else "error"), err
    doc = json.loads((Path(res["case_dir"]) / "result.json").read_text(encoding="utf-8"))
    rows = db.build_rows(doc, booking_id, report.Names(prompt.load_criteria()), publish=deps.publish)
    rows["audit"]["transcript_uri"] = gcs.transcript_uri(booking_id)
    return "done", rows


def _finish(booking_id: str, run_id: int, attempt: int, deps: Deps, outcome) -> dict:
    kind, payload = outcome
    if kind == "transient":
        return _wait(booking_id, run_id, attempt, deps, f"Chấm lỗi tạm quá số lần thử: {payload[:300]}", SCORING_LIMIT)
    if kind != "done":
        return _fail(booking_id, run_id, deps, kind, payload[:500])
    if not deps.store.save_result(payload, run_id=run_id):
        return {"status": "stale"}
    return {"status": payload["evaluation"]["status"], "overall": payload["evaluation"]["overall"]}


def _fail(booking_id: str, run_id: int, deps: Deps, status: str, error: str) -> dict:
    if not deps.store.fail(booking_id, status, error, run_id=run_id):
        return {"status": "stale"}
    return {"status": status}


def _wait(booking_id: str, run_id: int, attempt: int, deps: Deps, timeout_msg: str, limit: int = MAX_ATTEMPTS) -> dict:
    if attempt + 1 >= limit:
        return _fail(booking_id, run_id, deps, "error", timeout_msg)
    if not deps.store.touch(booking_id, attempt + 1, run_id=run_id):
        return {"status": "stale"}
    deps.enqueue(booking_id, run_id, attempt + 1, POLL_DELAY_SEC)
    return {"status": "waiting", "attempt": attempt + 1}
