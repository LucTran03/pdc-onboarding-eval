"""Transcript onboarding trên GCS: STT ghi transcripts/onboarding/<booking_id>.json; obeval chỉ có quyền ĐỌC prefix này."""
from __future__ import annotations

import os
from pathlib import Path

BUCKET = os.environ.get("OBEVAL_TRANSCRIPT_BUCKET", "teenup-transcripts")
PREFIX = "transcripts/onboarding/"


def transcript_uri(booking_id: str) -> str:
    return f"gs://{BUCKET}/{PREFIX}{booking_id}.json"


def download(uri: str, dest: Path) -> bool:
    """Tải về dest; False nếu file chưa có (STT chưa ghi xong)."""
    from google.api_core.exceptions import NotFound
    from google.cloud import storage

    bucket, _, obj = uri[len("gs://"):].partition("/")
    try:
        storage.Client().bucket(bucket).blob(obj).download_to_filename(str(dest))
        return True
    except NotFound:
        return False
