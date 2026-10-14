"""Tên file recording Meet → mã học sinh + giờ bắt đầu ghi; chọn booking onboarding khớp.

Tên thật: "TeenCare - Gia sư tâm lý 1_1 Onboarding -TC…_PH … - 2026_10_11 20_29 GMT+07_00 – Recording.mp4".
Cùng định dạng buổi 1:1 hàng tuần mà session-on-trigger đang đọc (app/api/v1/endpoints/sessions.py,
drive_webhook). Cửa sổ ±90 phút lấy từ đo đạc ở đó: |giờ tên file − giờ buổi| ≤ 90' phủ 98%, phần
còn lại là khớp nhầm.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

VN = timezone(timedelta(hours=7))
ONBOARDING_RE = re.compile(r"1[:_]1 onboarding")  # Meet ghi 1_1; Apps Script nhận cả 1:1
WINDOW = timedelta(minutes=90)

_TC = re.compile(r"\b(TC\d+)", re.IGNORECASE)
_DT = re.compile(r"(\d{4})[_:/-](\d{2})[_:/-](\d{2})\s+(\d{2})[:_](\d{2})")
_TZ = re.compile(r"GMT([+-])(\d{2})(?:[:_]?(\d{2}))?", re.IGNORECASE)


@dataclass(frozen=True)
class RecordingName:
    student_code: str
    recorded_at: datetime  # luôn có múi giờ


def _normalize(name: str) -> str:
    s = unicodedata.normalize("NFKC", name or "")
    for a, b in (("–", "-"), ("—", "-"), (" ", " "), (" ", " ")):
        s = s.replace(a, b)
    return s.strip()


def is_onboarding(name: str) -> bool:
    return ONBOARDING_RE.search(_normalize(name).lower()) is not None


def parse(name: str) -> RecordingName | None:
    s = _normalize(name)
    tc, dt = _TC.search(s), _DT.search(s)
    if not tc or not dt:
        return None
    y, mo, d, h, mi = (int(x) for x in dt.groups())
    try:
        tz = VN  # tên không ghi múi giờ → giờ Việt Nam, như session-on-trigger
        m = _TZ.search(s, dt.end())
        if m:
            sign = 1 if m.group(1) == "+" else -1
            tz = timezone(sign * timedelta(hours=int(m.group(2)), minutes=int(m.group(3) or 0)))
        at = datetime(y, mo, d, h, mi, tzinfo=tz)
    except ValueError:  # ngày giờ vô lý hoặc offset ngoài (-24h, +24h) như GMT+99_00
        return None
    return RecordingName(tc.group(1).upper(), at)


def pick_booking(rows: list[dict], recorded_at: datetime, window: timedelta = WINDOW) -> dict | None:
    """Booking cùng mã học sinh gần giờ ghi nhất trong ±window; bỏ buổi đã huỷ."""
    best = None
    for r in rows:
        if r.get("status") == "cancelled":
            continue
        diff = abs(r["start_at"] - recorded_at)
        if diff <= window and (best is None or diff < best[0]):
            best = (diff, r)
    return best[1] if best else None
