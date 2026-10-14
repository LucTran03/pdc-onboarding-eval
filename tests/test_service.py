"""Điều phối một ca onboarding bằng đồ giả: không DB, không GCS, không model (dùng replay)."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))

from obeval import pipeline, prompt, recording, service  # noqa: E402
from test_obeval import SEGS, fake_raw  # noqa: E402

NOW = datetime(2026, 10, 11, 14, 0, tzinfo=timezone.utc)
NAME = ("TeenCare - Gia sư tâm lý 1_1 Onboarding -TC99999_PH Nguyễn Văn A - 0900000000"
        " - 2026_10_11 20_29 GMT+07_00 – Recording.mp4")
FILE = {"id": "file-1", "name": NAME, "webViewLink": "https://drive.google.com/file/d/file-1/view"}
BOOKING = {"id": "b-1", "student_code": "TC99999", "status": "scheduled",
           "start_at": datetime(2026, 10, 11, 20, 30, tzinfo=recording.VN)}
ROLE = {"SPEAKER_00": "mentor", "SPEAKER_01": "parent"}


def stt_json(name="diarized-v1"):
    return {"pipeline": name, "session_flag": "ok", "duration_sec": 2700,
            "segments": [{"start_sec": t, "end_sec": t + 5, "text": x, "role": ROLE[s]} for t, s, x in SEGS]}


class FakeStore:
    def __init__(self, bookings=(BOOKING,), ev=None):
        self.bookings, self.ev = list(bookings), (dict(ev) if ev else None)
        self.unmatched, self.saved, self.starts = [], None, 0
        self.touches, self.on_save = [], None

    def booking_candidates(self, code, around):
        return [b for b in self.bookings if b["student_code"] == code]

    def evaluation(self, bid):
        return dict(self.ev) if self.ev else None

    def start(self, booking, file):
        self.starts += 1
        self.ev = {"booking_id": booking["id"], "status": "processing", "recording_file_id": file["id"],
                   "recording_url": file["webViewLink"], "run_id": 7, "attempts": 0, "updated_at": NOW,
                   "session_date": "2026-10-11"}
        return 7

    def _current(self, run_id):
        return run_id is None or (self.ev is not None and self.ev.get("run_id") == run_id)

    def touch(self, bid, attempts, run_id=None):
        self.touches.append(attempts)
        if not self._current(run_id):
            return False
        self.ev["attempts"] = attempts
        return True

    def fail(self, bid, status, error, run_id=None):
        if not self._current(run_id):
            return False
        self.ev.update(status=status, error=error)
        return True

    def save_result(self, rows, run_id=None):
        if self.on_save:
            self.on_save(self)
        if not self._current(run_id):
            return False
        self.saved = rows
        self.ev["status"] = rows["evaluation"]["status"]
        return True

    def record_unmatched(self, file, reason):
        self.unmatched.append((file["id"], reason))


class Case(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = Path(self.tmp.name)
        self.raw = d / "raw.json"
        self.raw.write_text(json.dumps(fake_raw(), ensure_ascii=False), encoding="utf-8")
        self.script = d / "script.txt"
        self.script.write_text("Kịch bản thử", encoding="utf-8")
        self.enqueued, self.evaluated = [], 0
        self.stt_state, self.stt_doc = "processing", stt_json()
        self.eval_result = None

    def tearDown(self):
        self.tmp.cleanup()

    def deps(self, store, publish=False):
        def request(bid, url):
            if isinstance(self.stt_state, Exception):
                raise self.stt_state
            return self.stt_state

        def download(uri, dest):
            if self.stt_doc is None:
                return False
            dest.write_text(json.dumps(self.stt_doc, ensure_ascii=False), encoding="utf-8")
            return True

        def evaluate(path, meta, out_root):
            self.evaluated += 1
            if self.eval_result is not None:
                return self.eval_result
            old = prompt.load_script.__defaults__
            prompt.load_script.__defaults__ = (self.script,)
            try:
                return pipeline.run_case(path, meta, out_root=out_root, replay=self.raw)
            finally:
                prompt.load_script.__defaults__ = old

        return service.Deps(store=store, request_transcript=request, download=download,
                            enqueue=lambda *a: self.enqueued.append(a), evaluate=evaluate,
                            publish=publish, now=lambda: NOW)


class TestRegister(Case):
    def test_ignores_weekly_recording(self):
        st = FakeStore()
        out = service.register({**FILE, "name": NAME.replace("1_1 Onboarding", "Mentor 1_1 hàng tuần")}, self.deps(st))
        self.assertEqual(out["status"], "ignored")
        self.assertEqual((st.starts, st.unmatched, self.enqueued), (0, [], []))

    def test_unparsable_and_no_booking_are_recorded(self):
        st = FakeStore(bookings=())
        self.assertEqual(service.register({**FILE, "name": "1_1 Onboarding Recording.mp4"}, self.deps(st))["reason"],
                         "unparsable_name")
        self.assertEqual(service.register(FILE, self.deps(st))["reason"], "no_booking")
        self.assertEqual(st.unmatched, [("file-1", "unparsable_name"), ("file-1", "no_booking")])

    def test_register_queues_once(self):
        st = FakeStore()
        self.assertEqual(service.register(FILE, self.deps(st))["status"], "queued")
        self.assertEqual(service.register(FILE, self.deps(st))["status"], "in_progress")
        # lần 2 gửi lại enqueue (Cloud Tasks dedupe theo tên task) nhưng KHÔNG bắt đầu run mới
        self.assertEqual((st.starts, self.enqueued), (1, [("b-1", 7, 0, 0), ("b-1", 7, 0, 0)]))

    def test_enqueue_failure_is_recoverable_by_next_register(self):
        st, calls = FakeStore(), []

        def flaky(*a):
            calls.append(a)
            if len(calls) == 1:
                raise RuntimeError("tasks down")
        deps = self.deps(st)
        deps.enqueue = flaky
        with self.assertRaises(RuntimeError):
            service.register(FILE, deps)
        self.assertEqual(service.register(FILE, deps)["status"], "in_progress")
        self.assertEqual((st.starts, calls), (1, [("b-1", 7, 0, 0), ("b-1", 7, 0, 0)]))

    def test_different_file_same_booking_starts_new_run(self):
        st = FakeStore()
        service.register(FILE, self.deps(st))
        other = {**FILE, "id": "file-2"}
        self.assertEqual(service.register(other, self.deps(st))["status"], "queued")
        self.assertEqual((st.starts, len(self.enqueued)), (2, 2))

    def _other_file_case(self, status):
        st = FakeStore(ev={"status": status, "recording_file_id": "file-1", "run_id": 3, "updated_at": NOW})
        return st, service.register({**FILE, "id": "file-2"}, self.deps(st))

    def test_different_file_when_done_is_duplicate(self):
        st, out = self._other_file_case("done")
        self.assertEqual(out, {"status": "duplicate", "booking_id": "b-1"})
        self.assertEqual((st.starts, st.unmatched, self.enqueued), (0, [("file-2", "duplicate_recording")], []))

    def test_different_file_when_insufficient_is_duplicate(self):
        st, out = self._other_file_case("insufficient")
        self.assertEqual(out["status"], "duplicate")
        self.assertEqual((st.starts, st.unmatched, self.enqueued), (0, [("file-2", "duplicate_recording")], []))

    def test_different_file_when_processing_starts_new_run(self):
        st, out = self._other_file_case("processing")
        self.assertEqual(out["status"], "queued")
        self.assertEqual((st.starts, st.unmatched, self.enqueued), (1, [], [("b-1", 7, 0, 0)]))

    def test_different_file_when_error_starts_new_run(self):
        st, out = self._other_file_case("error")
        self.assertEqual(out["status"], "queued")
        self.assertEqual((st.starts, st.unmatched, self.enqueued), (1, [], [("b-1", 7, 0, 0)]))

    def test_restarts_stale_processing(self):
        st = FakeStore(ev={"status": "processing", "recording_file_id": "file-1", "run_id": 3,
                           "updated_at": NOW - timedelta(hours=1)})
        self.assertEqual(service.register(FILE, self.deps(st))["status"], "queued")
        self.assertEqual((st.starts, self.enqueued), (1, [("b-1", 7, 0, 0)]))

    def test_already_done_same_file_not_rescored(self):
        st = FakeStore(ev={"status": "done", "recording_file_id": "file-1", "run_id": 3, "updated_at": NOW})
        self.assertEqual(service.register(FILE, self.deps(st))["status"], "already_done")
        self.assertEqual(self.enqueued, [])


class TestAdvance(Case):
    def started(self):
        st = FakeStore()
        service.register(FILE, self.deps(st))
        self.enqueued.clear()
        return st

    def test_advance_stale_run_ignored(self):
        st = self.started()
        self.assertEqual(service.advance("b-1", 999, 0, self.deps(st))["status"], "stale")
        self.assertEqual(self.enqueued, [])

    def test_waits_while_stt_processing(self):
        st = self.started()
        out = service.advance("b-1", 7, 0, self.deps(st))
        self.assertEqual(out, {"status": "waiting", "attempt": 1})
        self.assertEqual(self.enqueued, [("b-1", 7, 1, service.POLL_DELAY_SEC)])
        self.assertEqual(st.ev["attempts"], 1)

    def test_done_but_file_missing_keeps_waiting_then_times_out(self):
        st = self.started()
        self.stt_state, self.stt_doc = "done", None
        self.assertEqual(service.advance("b-1", 7, 0, self.deps(st))["status"], "waiting")
        out = service.advance("b-1", 7, service.MAX_ATTEMPTS - 1, self.deps(st))
        self.assertEqual((out["status"], st.ev["status"]), ("error", "error"))

    def test_temp_transcript_transient_waits_permanent_fails(self):
        st = self.started()
        self.stt_state = service.TransientError("503")
        self.assertEqual(service.advance("b-1", 7, 0, self.deps(st))["status"], "waiting")
        self.stt_state = RuntimeError("HTTP 400 gcs_uri is required")
        self.assertEqual(service.advance("b-1", 7, 1, self.deps(st))["status"], "error")
        self.assertIn("temp-transcript", st.ev["error"])

    def test_stt_error_fails(self):
        st = self.started()
        self.stt_state = "error"
        self.assertEqual(service.advance("b-1", 7, 0, self.deps(st))["status"], "error")

    def test_advance_scores_and_saves_unpublished(self):
        st = self.started()
        self.stt_state = "done"
        out = service.advance("b-1", 7, 0, self.deps(st))
        self.assertEqual(out["status"], "done")  # replay của fake_raw() cho kết quả done
        ev = st.saved["evaluation"]
        self.assertEqual((ev["booking_id"], ev["published_at"], len(st.saved["steps"])), ("b-1", None, 37))
        self.assertEqual(st.saved["audit"]["transcript_uri"],
                         "gs://teenup-transcripts/transcripts/onboarding/b-1.json")

    def test_publish_flag_sets_published_at(self):
        st = self.started()
        self.stt_state = "done"
        service.advance("b-1", 7, 0, self.deps(st, publish=True))
        self.assertIsNotNone(st.saved["evaluation"]["published_at"])

    def test_advance_without_roles_is_insufficient(self):
        for name in ("legacy-backlog", "legacy-long", "legacy-fallback"):
            st = self.started()
            self.stt_state, self.stt_doc, self.evaluated = "done", {**stt_json(name), "segments": [
                {"start_sec": t, "end_sec": t + 5, "text": x} for t, _, x in SEGS]}, 0
            self.assertEqual(service.advance("b-1", 7, 0, self.deps(st))["status"], "insufficient", name)
            self.assertEqual((self.evaluated, st.saved), (0, None))

    def test_transient_model_error_retries_permanent_fails(self):
        st = self.started()
        self.stt_state = "done"
        self.eval_result = {"state": "error", "error": "Mọi lần gọi model đều lỗi: 429 RESOURCE_EXHAUSTED"}
        self.assertEqual(service.advance("b-1", 7, 0, self.deps(st))["status"], "waiting")
        self.assertEqual((self.enqueued, st.touches), ([("b-1", 7, 1, service.POLL_DELAY_SEC)], [1]))
        self.eval_result = {"state": "error", "error": "Transcript rỗng — không chấm"}
        self.assertEqual(service.advance("b-1", 7, 1, self.deps(st))["status"], "error")


    def test_empty_transcript_is_insufficient_without_model_call(self):
        st = self.started()
        self.stt_state, self.stt_doc = "done", {**stt_json(), "segments": []}
        self.assertEqual(service.advance("b-1", 7, 0, self.deps(st))["status"], "insufficient")
        self.assertEqual((self.evaluated, st.ev["status"], st.saved), (0, "insufficient", None))

    def test_download_oserror_waits_other_exception_fails(self):
        st = self.started()
        self.stt_state = "done"
        deps = self.deps(st)
        deps.download = lambda uri, dest: (_ for _ in ()).throw(OSError("net"))
        self.assertEqual(service.advance("b-1", 7, 0, deps)["status"], "waiting")
        deps.download = lambda uri, dest: (_ for _ in ()).throw(RuntimeError("boom"))
        self.assertEqual(service.advance("b-1", 7, 1, deps)["status"], "error")
        self.assertEqual((st.ev["status"], st.ev["error"]), ("error", "RuntimeError: boom"))

    def test_store_failure_is_not_swallowed(self):
        st = self.started()
        self.stt_state = "done"

        def down(*a, **k):
            raise ConnectionError("db down")
        st.on_save = down
        with self.assertRaises(ConnectionError):
            service.advance("b-1", 7, 0, self.deps(st))
        self.assertEqual(st.ev["status"], "processing")

    def test_superseded_run_is_stale_and_not_overwritten(self):
        st = self.started()
        self.stt_state = "done"
        st.on_save = lambda s: s.ev.update(run_id=8)  # lượt mới bắt đầu giữa lúc đang chấm
        self.assertEqual(service.advance("b-1", 7, 0, self.deps(st))["status"], "stale")
        self.assertEqual((st.saved, st.ev["status"], st.ev["run_id"]), (None, "processing", 8))

    def test_scoring_retry_budget_is_larger_than_stt_budget(self):
        st = self.started()
        self.stt_state = "done"
        self.eval_result = {"state": "error", "error": "503 UNAVAILABLE"}
        out = service.advance("b-1", 7, service.MAX_ATTEMPTS - 1, self.deps(st))
        self.assertEqual(out, {"status": "waiting", "attempt": service.MAX_ATTEMPTS})
        self.assertEqual(self.enqueued[-1], ("b-1", 7, service.MAX_ATTEMPTS, service.POLL_DELAY_SEC))
        out = service.advance("b-1", 7, service.MAX_ATTEMPTS + service.SCORING_RETRIES - 1, self.deps(st))
        self.assertEqual((out["status"], st.ev["status"]), ("error", "error"))

    def test_google_transient_errors_wait_others_fail(self):
        st = self.started()
        self.stt_state = "done"
        deps = self.deps(st)
        for name in ("ServiceUnavailable", "TooManyRequests", "InternalServerError", "GatewayTimeout",
                     "DeadlineExceeded", "TransportError"):
            exc_cls = type(name, (Exception,), {"__module__": "google.api_core.exceptions"})
            deps.download = lambda uri, dest, c=exc_cls: (_ for _ in ()).throw(c("tạm"))
            st.ev["status"] = "processing"
            self.assertEqual(service.advance("b-1", 7, 0, deps)["status"], "waiting", name)
        # cùng tên nhưng không thuộc google.* → lỗi cố định; google.* nhưng tên khác (vd NotFound) → lỗi cố định
        for module, name in (("myapp.errors", "ServiceUnavailable"), ("google.api_core.exceptions", "NotFound")):
            exc_cls = type(name, (Exception,), {"__module__": module})
            deps.download = lambda uri, dest, c=exc_cls: (_ for _ in ()).throw(c("x"))
            st.ev["status"] = "processing"
            self.assertEqual(service.advance("b-1", 7, 0, deps)["status"], "error", f"{module}.{name}")

    def test_scoring_window_transient_request_or_missing_file_keeps_waiting(self):
        st = self.started()
        attempt = service.MAX_ATTEMPTS  # đã sang cửa sổ chấm lại: ngân sách chờ STT hết từ lâu
        self.stt_state = service.TransientError("503")
        out = service.advance("b-1", 7, attempt, self.deps(st))
        self.assertEqual(out, {"status": "waiting", "attempt": attempt + 1})
        self.stt_state, self.stt_doc = "done", None
        out = service.advance("b-1", 7, attempt, self.deps(st))
        self.assertEqual(out, {"status": "waiting", "attempt": attempt + 1})

    def test_scoring_window_exhausted_message(self):
        st = self.started()
        self.stt_state = service.TransientError("503")
        out = service.advance("b-1", 7, service.SCORING_LIMIT - 1, self.deps(st))
        self.assertEqual((out["status"], st.ev["status"]), ("error", "error"))
        self.assertIn("chấm lại quá số lần thử", st.ev["error"])
        self.assertNotIn("STT chưa xong", st.ev["error"])

    def test_transient_marker_is_word_bounded(self):
        self.assertIsNone(service.TRANSIENT_RE.search("Còn 4290 tiêu chí lỗi"))
        self.assertIsNotNone(service.TRANSIENT_RE.search("HTTP 429 Too Many Requests"))


class TestToken(unittest.TestCase):
    def test_token_ok(self):
        self.assertTrue(service.token_ok("abc", "abc"))
        self.assertFalse(service.token_ok("abd", "abc"))
        self.assertFalse(service.token_ok(None, "abc"))
        self.assertFalse(service.token_ok("", ""))  # chưa cấu hình token thì từ chối hết

    def test_token_ok_ignores_surrounding_whitespace(self):
        # Secret tạo bằng `echo` có dấu xuống dòng ở cuối không được làm hỏng xác thực.
        self.assertTrue(service.token_ok("abc", "abc\n"))
        self.assertTrue(service.token_ok("abc\n", "abc"))
        self.assertTrue(service.token_ok("  abc ", "abc\r\n"))
        self.assertFalse(service.token_ok("abd", "abc\n"))
        self.assertFalse(service.token_ok("abc", "abcd\n"))

    def test_token_ok_empty_expected_rejects(self):
        self.assertFalse(service.token_ok("", "\n"))
        self.assertFalse(service.token_ok("abc", "  "))
        self.assertFalse(service.token_ok("abc", None))


if __name__ == "__main__":
    unittest.main()
