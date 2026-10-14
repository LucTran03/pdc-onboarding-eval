"""SQL của Store (run_id guard) bằng kết nối psycopg giả — không DB thật."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from obeval.store import Store  # noqa: E402


class Cur:
    def __init__(self, log, row, rowcount):
        self.log, self.row, self.rowcount = log, row, rowcount

    def execute(self, sql, args=None):
        self.log.append((sql, list(args or [])))
        return self

    def executemany(self, sql, seq):
        self.log.append((sql, list(seq)))

    def fetchone(self):
        return self.row

    def cursor(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def make_store(row=None, rowcount=1):
    log = []
    st = Store("postgresql://x")
    st._conn = lambda: Cur(log, row, rowcount)
    return st, log


ROWS = {"evaluation": {"booking_id": "b-1", "status": "done"},
        "steps": [{"booking_id": "b-1", "criterion_id": 1, "activity": "a", "status": "ok"}],
        "audit": {"booking_id": "b-1"}}


class TestStoreGuard(unittest.TestCase):
    def test_touch_and_fail_guard_only_when_run_id_given(self):
        for call in (lambda s, **k: s.touch("b-1", 2, **k), lambda s, **k: s.fail("b-1", "error", "x", **k)):
            st, log = make_store()
            self.assertTrue(call(st))
            self.assertNotIn("run_id = %s", log[-1][0])
            st, log = make_store()
            self.assertTrue(call(st, run_id=7))
            self.assertTrue(log[-1][0].endswith("and run_id = %s"))
            self.assertEqual(log[-1][1][-1], 7)
            st, _ = make_store(rowcount=0)
            self.assertFalse(call(st, run_id=7))

    def test_save_result_skips_write_on_mismatch_or_missing(self):
        for row in ({"run_id": 8}, None):
            st, log = make_store(row=row)
            self.assertFalse(st.save_result(ROWS, run_id=7))
            self.assertEqual(len(log), 1)
            self.assertIn("for update", log[0][0])

    def test_save_result_writes_when_run_matches_or_unguarded(self):
        st, log = make_store(row={"run_id": 7})
        self.assertTrue(st.save_result(ROWS, run_id=7))
        self.assertGreater(len(log), 3)
        st, log = make_store()
        self.assertTrue(st.save_result(ROWS))
        self.assertFalse(any("for update" in sql for sql, _ in log))

    def test_start_resets_published_at(self):
        # Chấm lại booking cũ: bản báo cáo đã công bố của recording trước không được còn hiện cho Mentor.
        from datetime import datetime, timezone

        st, log = make_store()
        booking = {"id": "b-1", "start_at": datetime(2026, 10, 11, 13, 0, tzinfo=timezone.utc)}
        run_id = st.start(booking, {"id": "f1", "webViewLink": "https://drive/f1"})
        sql, args = log[0]
        cols = [c.strip() for c in sql.split("(", 1)[1].split(")", 1)[0].split(",")]
        self.assertIn("published_at", cols)
        self.assertIsNone(args[cols.index("published_at")])
        self.assertEqual(args[cols.index("run_id")], run_id)
        self.assertIn("published_at = excluded.published_at", sql)


if __name__ == "__main__":
    unittest.main()
