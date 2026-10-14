"""Đọc / ghi DB đặt lịch bằng role riêng `obeval_writer` (sql/003_obeval_writer.sql).

OBEVAL_DB_DSN = chuỗi kết nối Postgres của role đó (Supavisor: user `obeval_writer.<project_ref>`).
Role chỉ đọc 6 cột của bookings và ghi các bảng onboarding_*; không dùng service-role key.
`prepare_threshold=None`: pooler chế độ transaction không giữ prepared statement giữa các lần gọi.
"""
from __future__ import annotations

import os
import time
from datetime import datetime, timedelta

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from .recording import VN

EVENT_TYPE_NAME = "Gia sư tâm lý 1:1 Onboarding"
_EV_COLS = "booking_id::text as booking_id, status, updated_at, recording_file_id, recording_url, run_id, attempts, session_date"


def _val(v):
    return Jsonb(v) if isinstance(v, (dict, list)) else v


def _upsert(cur, table: str, row: dict, conflict: tuple[str, ...]) -> None:
    cols = list(row)  # tên cột do code đặt, không lấy từ người dùng
    sets = ", ".join(f"{c} = excluded.{c}" for c in cols if c not in conflict)
    cur.execute(
        f"insert into public.{table} ({', '.join(cols)}) values ({', '.join(['%s'] * len(cols))}) "
        f"on conflict ({', '.join(conflict)}) do update set {sets}",
        [_val(row[c]) for c in cols])


class Store:
    def __init__(self, dsn: str | None = None):
        self.dsn = dsn or os.environ.get("OBEVAL_DB_DSN")
        if not self.dsn:
            raise RuntimeError("Thiếu OBEVAL_DB_DSN")

    def _conn(self):
        return psycopg.connect(self.dsn, row_factory=dict_row, prepare_threshold=None)

    def booking_candidates(self, student_code: str, around: datetime, days: int = 2) -> list[dict]:
        sql = ("select b.id::text as id, b.start_at, b.status, b.mentor_id::text as mentor_id "
               "from public.bookings b join public.event_types et on et.id = b.event_type_id "
               "where et.name = %s and upper(b.student_code) = %s and b.start_at between %s and %s")
        with self._conn() as c:
            return c.execute(sql, (EVENT_TYPE_NAME, student_code.upper(),
                                   around - timedelta(days=days), around + timedelta(days=days))).fetchall()

    def evaluation(self, booking_id: str) -> dict | None:
        with self._conn() as c:
            return c.execute(f"select {_EV_COLS} from public.onboarding_evaluations where booking_id = %s",
                             (booking_id,)).fetchone()

    def start(self, booking: dict, file: dict) -> int:
        run_id = time.time_ns() // 1_000_000
        row = {"booking_id": booking["id"], "status": "processing", "error": None,
               "session_date": booking["start_at"].astimezone(VN).date(),
               "recording_file_id": file["id"], "recording_url": file["webViewLink"],
               "run_id": run_id, "attempts": 0,
               "published_at": None}  # chấm lại: bản báo cáo đã công bố của recording trước không còn hiện cho Mentor
        with self._conn() as c:
            _upsert(c.cursor(), "onboarding_evaluations", row, ("booking_id",))
        return run_id

    def touch(self, booking_id: str, attempts: int, run_id: int | None = None) -> bool:
        """False nếu đã có lượt chấm mới hơn (run_id lệch) — không ghi gì."""
        sql, args = "update public.onboarding_evaluations set attempts = %s where booking_id = %s", [attempts, booking_id]
        if run_id is not None:
            sql, args = sql + " and run_id = %s", args + [run_id]
        with self._conn() as c:
            return c.execute(sql, args).rowcount > 0

    def fail(self, booking_id: str, status: str, error: str, run_id: int | None = None) -> bool:
        sql = "update public.onboarding_evaluations set status = %s, error = %s where booking_id = %s"
        args = [status, error[:1000], booking_id]
        if run_id is not None:
            sql, args = sql + " and run_id = %s", args + [run_id]
        with self._conn() as c:
            return c.execute(sql, args).rowcount > 0

    def save_result(self, rows: dict, run_id: int | None = None) -> bool:
        """evaluation + 37 steps + audit trong MỘT transaction (chấm lại thì thay cả 37 dòng).

        Có run_id: khoá dòng rồi chỉ ghi khi run_id còn khớp; lệch (đã có lượt mới) → không ghi, trả False.
        """
        ev = rows["evaluation"]
        with self._conn() as c, c.cursor() as cur:
            if run_id is not None:
                cur.execute("select run_id from public.onboarding_evaluations where booking_id = %s for update",
                            (ev["booking_id"],))
                cur_row = cur.fetchone()
                if cur_row is None or cur_row["run_id"] != run_id:
                    return False
            _upsert(cur, "onboarding_evaluations", ev, ("booking_id",))
            cur.execute("delete from public.onboarding_evaluation_steps where booking_id = %s", (ev["booking_id"],))
            cur.executemany(
                "insert into public.onboarding_evaluation_steps (booking_id, criterion_id, activity, status) "
                "values (%s, %s, %s, %s)",
                [(s["booking_id"], s["criterion_id"], s["activity"], s["status"]) for s in rows["steps"]])
            _upsert(cur, "onboarding_evaluation_audit", rows["audit"], ("booking_id",))
        return True

    def record_unmatched(self, file: dict, reason: str) -> None:
        with self._conn() as c:
            c.execute(
                "insert into public.onboarding_recording_unmatched (file_id, file_name, reason) values (%s, %s, %s) "
                "on conflict (file_id) do update set reason = excluded.reason, last_seen_at = now()",
                (file["id"], file.get("name") or "", reason))

    def publish_done(self) -> int:
        """Sau khi qua cổng chất lượng: cho Mentor xem mọi ca đã chấm xong."""
        with self._conn() as c:
            cur = c.execute("update public.onboarding_evaluations set published_at = now() "
                            "where status = 'done' and published_at is null")
            return cur.rowcount
