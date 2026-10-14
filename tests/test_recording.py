"""Đọc tên file recording Meet và chọn booking — thuần stdlib."""
from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from obeval import recording  # noqa: E402

# Định dạng thật, tên / SĐT hư cấu
NAME = ("TeenCare - Gia sư tâm lý 1_1 Onboarding -TC99999_PH Nguyễn Văn A - Trần Bé B - 0900000000"
        " - 2026_10_11 20_29 GMT+07_00 – Recording.mp4")


def bk(i, hh, mm, status="scheduled"):
    return {"id": f"b{i}", "start_at": datetime(2026, 10, 11, hh, mm, tzinfo=recording.VN), "status": status}


class TestParse(unittest.TestCase):
    def test_real_format(self):
        r = recording.parse(NAME)
        self.assertEqual(r.student_code, "TC99999")
        self.assertEqual(r.recorded_at, datetime(2026, 10, 11, 20, 29, tzinfo=recording.VN))

    def test_absurd_offset_returns_none(self):
        self.assertIsNone(recording.parse(NAME.replace("GMT+07_00", "GMT+99_00")))
        self.assertIsNone(recording.parse(NAME.replace("GMT+07_00", "GMT-30_00")))

    def test_other_timezone(self):
        r = recording.parse(NAME.replace("GMT+07_00", "GMT+08_00"))
        self.assertEqual(r.recorded_at.astimezone(timezone.utc), datetime(2026, 10, 11, 12, 29, tzinfo=timezone.utc))

    def test_missing_timezone_means_vietnam(self):
        r = recording.parse(NAME.replace(" GMT+07_00", ""))
        self.assertEqual(r.recorded_at, datetime(2026, 10, 11, 20, 29, tzinfo=recording.VN))

    def test_unicode_variants(self):
        name = NAME.replace(" ", " ").replace("20_29", "20：29").replace("–", "—")
        r = recording.parse(name)
        self.assertEqual((r.student_code, r.recorded_at.hour, r.recorded_at.minute), ("TC99999", 20, 29))

    def test_unparsable(self):
        self.assertIsNone(recording.parse("Recording.mp4"))
        self.assertIsNone(recording.parse(NAME.replace("TC99999", "HS99999")))
        self.assertIsNone(recording.parse(NAME.replace("2026_10_11", "2026_13_45")))

    def test_is_onboarding(self):
        self.assertTrue(recording.is_onboarding(NAME))
        self.assertFalse(recording.is_onboarding(NAME.replace("1_1 Onboarding", "Mentor 1_1 hàng tuần")))

    def test_is_onboarding_accepts_colon_variant(self):
        self.assertTrue(recording.is_onboarding(NAME.replace("1_1 Onboarding", "1:1 Onboarding")))
        self.assertTrue(recording.is_onboarding(NAME.replace("1_1 Onboarding", "1：1 Onboarding")))
        self.assertFalse(recording.is_onboarding(NAME.replace("1_1 Onboarding", "1-1 Onboarding")))


class TestPickBooking(unittest.TestCase):
    AT = datetime(2026, 10, 11, 20, 29, tzinfo=recording.VN)

    def test_nearest_inside_window_and_skips_cancelled(self):
        rows = [bk(1, 19, 0), bk(2, 20, 30, "cancelled"), bk(3, 20, 0)]
        self.assertEqual(recording.pick_booking(rows, self.AT)["id"], "b3")

    def test_none_outside_window(self):
        self.assertIsNone(recording.pick_booking([bk(1, 18, 0), bk(2, 22, 30)], self.AT))

    def test_window_is_90_minutes_both_sides(self):
        self.assertEqual(recording.pick_booking([bk(1, 18, 59)], self.AT)["id"], "b1")
        self.assertIsNone(recording.pick_booking([bk(1, 18, 58)], self.AT))


if __name__ == "__main__":
    unittest.main()
