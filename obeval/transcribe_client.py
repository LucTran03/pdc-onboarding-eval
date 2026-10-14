"""Gọi temp-transcript: tải recording Drive → mp3 → gửi STT với profile=onboarding.

Lần đầu temp-transcript stream cả video sang mp3 ngay trong request (vài phút với file > 1 GB),
nên timeout dài. Gọi lại cùng booking_id thì nó trả trạng thái job đã có.
"""
from __future__ import annotations

import http.client
import json
import os
import urllib.error
import urllib.request

from .service import TransientError

TIMEOUT_SEC = 600


def request(booking_id: str, recording_url: str, opener=urllib.request.urlopen, base_url: str | None = None) -> str:
    base = (base_url or os.environ.get("OBEVAL_TEMP_TRANSCRIPT_URL", "")).rstrip("/")
    if not base:
        raise RuntimeError("Thiếu OBEVAL_TEMP_TRANSCRIPT_URL")
    body = {"gcs_uri": recording_url, "session_id": booking_id, "profile": "onboarding", "lang": "vi"}
    req = urllib.request.Request(f"{base}/beta/transcript", data=json.dumps(body).encode("utf-8"),
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        with opener(req, timeout=TIMEOUT_SEC) as r:
            return str(json.loads(r.read().decode("utf-8")).get("status") or "processing")
    except urllib.error.HTTPError as exc:
        detail = exc.read()[:300].decode("utf-8", "replace")
        if exc.code >= 500 or exc.code == 429:
            raise TransientError(f"HTTP {exc.code}: {detail}") from None
        raise RuntimeError(f"HTTP {exc.code}: {detail}") from None
    except (OSError, http.client.HTTPException, ValueError) as exc:  # URLError, timeout, ngắt kết nối, 200 không phải JSON
        raise TransientError(str(exc)) from None
