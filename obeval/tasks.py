"""Cloud Task gọi lại POST /v1/tasks/advance của chính obeval.

Tên task = adv-<booking>-<run_id>-<attempt>: gửi trùng thì Cloud Tasks trả AlreadyExists (bỏ qua);
chấm lại một booking có run_id mới nên không đụng tên task cũ (Cloud Tasks giữ tên đã dùng nhiều giờ).
dispatch_deadline 900 giây: một lượt chấm 3–4 phút; mặc định 10 phút dễ bị coi là lỗi rồi gửi lại.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone

DEADLINE = timedelta(seconds=900)


def build_task(parent: str, self_url: str, token: str, booking_id: str, run_id: int, attempt: int,
               delay_sec: int, now: datetime) -> dict:
    task = {
        "name": f"{parent}/tasks/adv-{booking_id}-{run_id}-{attempt}",
        "dispatch_deadline": DEADLINE,
        "http_request": {
            "url": f"{self_url.rstrip('/')}/v1/tasks/advance",
            "headers": {"Content-Type": "application/json", "X-Obeval-Token": token},
            "body": json.dumps({"booking_id": booking_id, "run_id": run_id, "attempt": attempt}).encode("utf-8"),
        },
    }
    if delay_sec:
        task["schedule_time"] = now + timedelta(seconds=delay_sec)
    return task


def enqueue_advance(booking_id: str, run_id: int, attempt: int, delay_sec: int) -> None:
    from google.api_core.exceptions import AlreadyExists
    from google.cloud import tasks_v2

    client = tasks_v2.CloudTasksClient()
    parent = client.queue_path(os.environ["OBEVAL_TASKS_PROJECT"], os.environ["OBEVAL_TASKS_LOCATION"],
                               os.environ["OBEVAL_TASKS_QUEUE"])
    task = build_task(parent, os.environ["OBEVAL_SELF_URL"], os.environ["OBEVAL_API_TOKEN"].strip(),
                      booking_id, run_id, attempt, delay_sec, datetime.now(timezone.utc))
    task["http_request"]["http_method"] = tasks_v2.HttpMethod.POST
    try:
        client.create_task(parent=parent, task=task)
    except AlreadyExists:
        pass
