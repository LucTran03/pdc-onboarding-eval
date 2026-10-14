"""HTTP cho Cloud Run: Apps Script báo recording mới; Cloud Tasks gọi lượt tiếp theo.

Cả hai endpoint kiểm header X-Obeval-Token (Secret Manager → OBEVAL_API_TOKEN). Lỗi ngoài dự kiến
trả 500 → Cloud Tasks / Apps Script gọi lại; service.advance tự bỏ qua lượt cũ theo run_id.
"""
from __future__ import annotations

import os
from functools import lru_cache

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel

from . import config, gcs, pipeline, service, tasks, transcribe_client

app = FastAPI(title="obeval")


class RecordingIn(BaseModel):
    id: str
    name: str
    webViewLink: str
    createdTime: str | None = None


class AdvanceIn(BaseModel):
    booking_id: str
    run_id: int
    attempt: int = 0


def _auth(x_obeval_token: str | None = Header(default=None)) -> None:
    """Phụ thuộc FastAPI: chạy trước khi kiểm body → request không có token luôn nhận 401, không lộ schema 422."""
    if not service.token_ok(x_obeval_token, os.environ.get("OBEVAL_API_TOKEN")):
        raise HTTPException(status_code=401, detail="unauthorized")


@lru_cache(maxsize=1)
def _deps() -> service.Deps:
    from .store import Store

    return service.Deps(
        store=Store(), request_transcript=transcribe_client.request, download=gcs.download,
        enqueue=tasks.enqueue_advance,
        evaluate=lambda path, meta, out_root: pipeline.run_case(path, meta, out_root=out_root),
        publish=config.PUBLISH)


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok", "service": "obeval"}


@app.post("/v1/recordings", dependencies=[Depends(_auth)])
def recordings(body: RecordingIn) -> dict:
    return service.register(body.model_dump(), _deps())


@app.post("/v1/tasks/advance", dependencies=[Depends(_auth)])
def advance(body: AdvanceIn) -> dict:
    return service.advance(body.booking_id, body.run_id, body.attempt, _deps())
