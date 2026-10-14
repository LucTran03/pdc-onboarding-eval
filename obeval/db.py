"""Ghi kết quả một ca lên DB đặt lịch (bảng onboarding_evaluations*, xem sql/001_onboarding_evaluations.sql).

Khoá là `bookings.id` (buổi onboarding chỉ tồn tại trong DB đặt lịch). Ghi qua Supabase REST bằng service key:
  OBEVAL_DB_URL=https://<ref>.supabase.co  OBEVAL_DB_KEY=<service / secret key>

`mentor_report` là bản NGẮN cho Mentor xem trong TeenCareBooking: % follow, phần chưa follow, cần cải thiện gì.
Không có trường trích dẫn (chỉ mốc giờ), nhưng phần chữ AI viết (lý do, câu nói mẫu) vẫn có thể nhắc tên / lời gia đình —
Mentor chỉ đọc được buổi của mình (RLS). Bản đầy đủ có trích dẫn nằm ở bảng audit (chỉ admin), mặc định không đẩy.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from . import config, prompt
from .report import STATUS_LABEL, Names, _deviations, _first_ts, _range_text, activity_ranges

REPORT_VERSION = 1


def mentor_report(result: dict, scores: dict, meta: dict, names: Names) -> dict:
    ranges = activity_ranges(result, names, meta.get("duration_sec"))
    return {
        "version": REPORT_VERSION,
        "overall": scores["overall"],
        "threshold": scores["good_threshold"],
        "classification": scores["classification_label"],
        "summary": names.humanize(result.get("summary_for_mentor") or ""),
        "activities": [{
            "activity": a["activity"],
            "name": names.act.get(a["activity"], {}).get("name", ""),
            "score": a["score"],
            "time": _range_text(ranges.get(a["activity"]), names.act.get(a["activity"], {}).get("duration", "")),
        } for a in scores["activities"]],
        "not_followed": [{
            "criterion_id": c["id"],
            "step": names.step(c["id"]),
            "activity": names.act_of(c["id"]),
            "status": c["status"],
            "status_label": STATUS_LABEL[c["status"]],
            "reason": names.humanize(c.get("rationale", "")),
            "missing": [str(m) for m in c.get("missing_elements") or []],
            "timestamp": _first_ts(c.get("evidence")),
        } for c in _deviations(result) if c["id"] in names.crit],
        "improvements": [{
            "criterion_id": it.get("criterion_id"),
            "step": names.step(it.get("criterion_id"), it.get("step_name", "")),
            "timestamp": _first_ts(it.get("evidence")),
            "problem": names.humanize(it.get("problem", "")),
            "suggestion": names.humanize(it.get("suggestion", "")),
            "suggested_script": it.get("suggested_script") or "",
        } for it in (result.get("improvements") or [])[:3]],
    }


def build_rows(doc: dict, booking_id: str, names: Names, *, publish: bool = False) -> dict:
    """doc = nội dung result.json → {evaluation, steps, audit} đúng cột của các bảng."""
    meta, scores, run = doc.get("meta") or {}, doc["scores"], doc.get("run") or {}
    result = {k: v for k, v in doc.items() if k not in ("meta", "scores", "run")}
    status = "insufficient" if scores["classification"] == "THIEU_DU_LIEU" else "done"
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    ranges = activity_ranges(result, names, meta.get("duration_sec"))
    evaluation = {
        "booking_id": booking_id,
        "status": status,
        "session_date": meta.get("session_date"),
        "duration_sec": int(meta["duration_sec"]) if meta.get("duration_sec") else None,
        "overall": round(scores["overall"], 4) if scores.get("overall") is not None else None,
        "threshold": scores["good_threshold"],
        "activities": [{**{k: a[k] for k in ("activity", "score", "counts")},
                        **{k: (ranges.get(a["activity"]) or {}).get(k) for k in ("start", "end", "estimated")}}
                       for a in scores["activities"]],
        "mentor_report": mentor_report(result, scores, meta, names),
        "flags": [{"id": f["id"], "script_instructed": bool(f.get("script_instructed"))}
                  for f in result.get("flags") or [] if f.get("id") in names.flag],
        "criteria_version": config.CRITERIA_VERSION,
        "model": run.get("model"),
        "scored_at": run.get("finished_at"),
        "published_at": now if publish else None,
        "error": None,
    }
    steps = [{"booking_id": booking_id, "criterion_id": c["id"], "activity": names.act_of(c["id"]), "status": c["status"]}
             for c in result.get("criteria") or [] if c.get("id") in names.crit]
    audit = {
        "booking_id": booking_id,
        "result": result,
        "stability": run.get("stability"),
        "ai_issues": run.get("ai_issues"),
        "quote_stats": run.get("quote_stats"),
        "transcript_warnings": run.get("transcript_warnings"),
        "cost_usd": run.get("cost_usd_est"),
        "usage": run.get("usage"),
    }
    return {"evaluation": evaluation, "steps": steps, "audit": audit}


class Rest:
    def __init__(self, url: str, key: str):
        self.base = url.rstrip("/") + "/rest/v1/"
        self.headers = {"apikey": key, "Authorization": f"Bearer {key}", "Content-Type": "application/json"}

    def call(self, method: str, path: str, body=None, prefer: str = "return=minimal"):
        data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, method=method, headers={**self.headers, "Prefer": prefer})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                raw = r.read()
                return json.loads(raw) if raw else None
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f"{method} {path}: HTTP {exc.code} {exc.read()[:300]!r}") from None


def push(case_dir: Path, booking_id: str, *, publish: bool = False, with_audit: bool = False,
         url: str | None = None, key: str | None = None) -> dict:
    url = url or os.environ.get("OBEVAL_DB_URL")
    key = key or os.environ.get("OBEVAL_DB_KEY")
    if not url or not key:
        raise SystemExit("Thiếu OBEVAL_DB_URL / OBEVAL_DB_KEY")
    doc = json.loads((Path(case_dir) / "result.json").read_text(encoding="utf-8"))
    rows = build_rows(doc, booking_id, Names(prompt.load_criteria()), publish=publish)
    api = Rest(url, key)
    upsert = "resolution=merge-duplicates,return=minimal"
    api.call("POST", "onboarding_evaluations?on_conflict=booking_id", rows["evaluation"], prefer=upsert)
    api.call("DELETE", f"onboarding_evaluation_steps?booking_id=eq.{booking_id}")  # chấm lại: thay cả 37 dòng
    api.call("POST", "onboarding_evaluation_steps", rows["steps"])
    if with_audit:
        api.call("POST", "onboarding_evaluation_audit?on_conflict=booking_id", rows["audit"], prefer=upsert)
    return {"booking_id": booking_id, "status": rows["evaluation"]["status"], "overall": rows["evaluation"]["overall"],
            "steps": len(rows["steps"]), "audit": with_audit, "published": publish}
