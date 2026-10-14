"""Lớp nối ra ngoài: đường dẫn GCS, phân loại lỗi temp-transcript, dựng Cloud Task — không gọi mạng."""
from __future__ import annotations

import http.client
import io
import json
import sys
import unittest
import urllib.error
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from obeval import gcs, service, tasks, transcribe_client  # noqa: E402


class Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def opener_returning(payload=None, http_code=None):
    seen = {}

    def op(req, timeout=None):
        seen["body"] = json.loads(req.data.decode("utf-8"))
        seen["url"] = req.full_url
        if http_code:
            raise urllib.error.HTTPError(req.full_url, http_code, "x", {}, io.BytesIO(b"boom"))
        return Resp(json.dumps(payload).encode("utf-8"))
    return op, seen


class TestAdapters(unittest.TestCase):
    def test_transcript_uri_is_onboarding_prefix(self):
        self.assertEqual(gcs.transcript_uri("b-1"), "gs://teenup-transcripts/transcripts/onboarding/b-1.json")

    def test_request_sends_onboarding_profile(self):
        op, seen = opener_returning({"status": "processing"})
        self.assertEqual(transcribe_client.request("b-1", "https://drive/x", opener=op, base_url="https://tt"), "processing")
        self.assertEqual(seen["url"], "https://tt/beta/transcript")
        self.assertEqual(seen["body"], {"gcs_uri": "https://drive/x", "session_id": "b-1",
                                        "profile": "onboarding", "lang": "vi"})

    def test_request_5xx_is_transient_4xx_is_not(self):
        op, _ = opener_returning(http_code=503)
        with self.assertRaises(service.TransientError):
            transcribe_client.request("b-1", "u", opener=op, base_url="https://tt")
        op, _ = opener_returning(http_code=400)
        with self.assertRaises(RuntimeError) as ctx:
            transcribe_client.request("b-1", "u", opener=op, base_url="https://tt")
        self.assertNotIsInstance(ctx.exception, service.TransientError)

    def test_request_network_and_bad_body_are_transient(self):
        def dropped(req, timeout=None):
            raise http.client.RemoteDisconnected("closed")
        with self.assertRaises(service.TransientError):
            transcribe_client.request("b-1", "u", opener=dropped, base_url="https://tt")
        with self.assertRaises(service.TransientError):
            transcribe_client.request("b-1", "u", opener=lambda req, timeout=None: Resp(b"<html>oops"),
                                      base_url="https://tt")

    def test_build_task(self):
        now = datetime(2026, 10, 14, tzinfo=timezone.utc)
        t = tasks.build_task("projects/p/locations/l/queues/q", "https://obeval", "tok", "b-1", 7, 2, 300, now)
        self.assertEqual(t["name"], "projects/p/locations/l/queues/q/tasks/adv-b-1-7-2")
        self.assertEqual(t["schedule_time"], now + timedelta(seconds=300))
        self.assertEqual(t["dispatch_deadline"], timedelta(seconds=900))
        req = t["http_request"]
        self.assertEqual((req["url"], req["headers"]["X-Obeval-Token"]), ("https://obeval/v1/tasks/advance", "tok"))
        self.assertEqual(json.loads(req["body"]), {"booking_id": "b-1", "run_id": 7, "attempt": 2})
        self.assertNotIn("schedule_time", tasks.build_task("q", "u", "t", "b", 1, 0, 0, now))

    def test_enqueue_advance_strips_token_newline(self):
        # Secret Manager tạo bằng `echo` có xuống dòng cuối: header gửi đi không được mang theo ký tự đó.
        import os
        import sys
        from unittest import mock

        env = {"OBEVAL_TASKS_PROJECT": "p", "OBEVAL_TASKS_LOCATION": "l", "OBEVAL_TASKS_QUEUE": "q",
               "OBEVAL_SELF_URL": "https://obeval", "OBEVAL_API_TOKEN": "tok" + chr(10)}
        fake_tasks = mock.MagicMock()
        fake_tasks.CloudTasksClient.return_value.queue_path.return_value = "projects/p/locations/l/queues/q"
        modules = {"google": mock.MagicMock(), "google.api_core": mock.MagicMock(),
                   "google.api_core.exceptions": mock.MagicMock(AlreadyExists=KeyError),
                   "google.cloud": mock.MagicMock(tasks_v2=fake_tasks), "google.cloud.tasks_v2": fake_tasks}
        with mock.patch.dict(os.environ, env), mock.patch.dict(sys.modules, modules):
            tasks.enqueue_advance("b-1", 7, 0, 0)
        sent = fake_tasks.CloudTasksClient.return_value.create_task.call_args.kwargs["task"]
        self.assertEqual(sent["http_request"]["headers"]["X-Obeval-Token"], "tok")


if __name__ == "__main__":
    unittest.main()
