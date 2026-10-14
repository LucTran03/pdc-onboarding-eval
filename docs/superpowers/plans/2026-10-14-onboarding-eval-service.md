# obeval chạy tự động trên Cloud Run — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Mỗi recording buổi "Gia sư tâm lý 1:1 Onboarding" tự đi từ Drive tới kết quả chấm trong DB đặt lịch, không ai thao tác tay; Mentor chỉ thấy kết quả sau khi qua cổng chất lượng.

**Architecture:** Script Apps Script đồng bộ recording đang chạy được thêm nhánh onboarding: chuyển recording sang folder Onboarding giới hạn quyền rồi gọi thẳng obeval (Cloud Run). obeval tự ghép file với `bookings`, gọi temp-transcript với `profile=onboarding`, tự hỏi lại qua Cloud Tasks (5 phút/lần, tối đa 3 giờ) cho tới khi STT ghi `transcripts/onboarding/<booking_id>.json`, rồi chấm và ghi DB bằng role riêng `obeval_writer`. Không đi qua session-on-trigger hay session-data-worker.

**Tech Stack:** Python 3.10+ (image 3.12), FastAPI + uvicorn, psycopg 3, google-cloud-storage, google-cloud-tasks, google-genai (Vertex, Gemini 2.5 Pro); Go (STT API); Google Apps Script; Supabase Postgres (RLS).

**Spec:** `docs/ke-hoach-trien-khai.md` + 5 thay đổi sếp duyệt ngày 14/10 (chép nguyên văn ở dưới). Chỗ nào hai nguồn khác nhau thì theo 5 thay đổi.

> 1. Skip session-on-trigger and session-data-worker: Apps Script calls obeval directly, and obeval looks up the booking and calls temp-transcript itself.
> 2. Add back the quality gate before mentors see anything (published_at stays empty until it passes): 5 sessions hand-scored by PDC, the 5 acceptance targets, and score variance on the same session of 5 points or less. Start this in week 1, in parallel with the build.
> 3. Store onboarding transcripts under transcripts/onboarding/, give obeval read access to that prefix only, and delete them after 90 days.
> 4. Booking DB prod: turn on RLS for the new tables so a mentor only sees their own sessions. obeval writes with its own limited role, not the service-role key.
> 5. Leave the pass threshold (80% now) for PDC to decide.

## Global Constraints

- Code obeval chạy được trên Python 3.10 (máy dev) và 3.12 (image); mọi file mới có `from __future__ import annotations`.
- Test obeval dùng `unittest`, chạy bằng `python -m unittest discover -s tests` trong `pdc-onboarding-eval`; test không gọi model, không gọi mạng, không cần GCP.
- obeval **không** dùng service-role key. Mọi đọc/ghi DB đặt lịch đi qua role `obeval_writer` bằng `OBEVAL_DB_DSN`.
- `obeval_writer` chỉ đọc 6 cột của `bookings`: `id, event_type_id, mentor_id, start_at, status, student_code` (không tên / SĐT / email phụ huynh).
- Loại buổi được chấm: `event_types.name = 'Gia sư tâm lý 1:1 Onboarding'` (đúng chuỗi này; không chấm "Onboarding Thailand", "Onboarding PH").
- Transcript onboarding nằm ở `gs://teenup-transcripts/transcripts/onboarding/<booking_id>.json`; obeval chỉ có quyền **đọc** prefix đó; lifecycle xoá sau **90 ngày**.
- `published_at` để trống cho tới khi qua cổng chất lượng: `OBEVAL_PUBLISH` mặc định `false`.
- Ngưỡng đạt đọc từ `OBEVAL_GOOD_THRESHOLD` (mặc định `0.80`), **PDC chốt giá trị**; không hard-code ở chỗ khác.
- Cổng chất lượng: 5 buổi PDC chấm tay; 5 chỉ tiêu: trùng phân loại tiêu chí ≥ 85%, lệch tỷ lệ toàn ca ≤ 5 điểm %, tìm đúng lỗi ≥ 85%, logic liên kết ≥ 80%, NF có dẫn chứng 100%; chấm lại cùng một buổi lệch ≤ 5 điểm %.
- Không đưa vào repo / image: kịch bản PDC (có số tài khoản ngân hàng), transcript, kết quả chấm, key, mật khẩu. Test chỉ dùng tên / SĐT hư cấu.
- Commit message không có dòng `Co-Authored-By` hay "Generated with Claude".
- DDL trên DB đặt lịch **prod** chỉ do chủ DB chạy; agent không chạy ghi lên prod.
- Không sửa luồng 1:1 hàng tuần: mọi thay đổi ở temp-transcript và STT là tham số mới, giá trị mặc định giữ nguyên hành vi cũ.

## Review Focus

1. Apps Script gọi lại cùng một file (lỗi mạng, chạy trùng trigger) → chỉ chấm một lần — test ở Task 7 (`test_register_queues_once`, `test_advance_stale_run_ignored`).
2. Tên file biến thể (thiếu `GMT+07_00`, dấu gạch dài, khoảng trắng không ngắt, múi giờ khác) → vẫn đọc đúng mã TC và giờ; file không phải onboarding bị bỏ qua — test ở Task 2.
3. Học sinh có hai booking onboarding gần nhau (đổi lịch, buổi huỷ) → chọn buổi gần giờ ghi nhất, bỏ buổi `cancelled`; ngoài ±90 phút thì vào danh sách không khớp — test ở Task 2 và Task 7.
4. STT trả bản không chia người nói (`legacy-backlog`, `legacy-long`, `legacy-fallback`) → ghi `insufficient`, không gọi model — test ở Task 7 (`test_advance_without_roles_is_insufficient`).
5. Gemini 429 / quota khi chấm → thử lại ở lượt sau, không đánh lỗi vĩnh viễn; temp-transcript báo xong nhưng file chưa có ở prefix mới → tiếp tục chờ rồi hết giờ thành `error` — test ở Task 7.

## Đầu vào cần có trước khi chạy Task 11–13

| Cần | Hỏi ai | Dùng ở |
|---|---|---|
| Tài khoản đang chạy Apps Script đồng bộ recording; recording onboarding có nằm trong thư mục "Google Meet" của chính tài khoản đó không | Nhật Anh | Task 12 |
| Đồng ý thêm nhánh onboarding vào script đồng bộ recording (sửa 5 hàm, thêm 1 file) | Nhật Anh | Task 12 |
| Project GCP đặt Cloud Run + Cloud Tasks của obeval | sếp | Task 11 |
| Project chứa bucket `teenup-transcripts`, bucket có bật uniform bucket-level access chưa | người quản trị GCP | Task 11 |
| Ai deploy STT (server GPU) và temp-transcript (Cloud Run `asia-east1`) | sếp / Nhật Anh | Task 9, 10 |
| Chủ DB đặt lịch prod chạy migration | sếp | Task 13 |

## File Structure

`pdc-onboarding-eval` (nhánh `feat/onboarding-service`):

| File | Trách nhiệm |
|---|---|
| `obeval/recording.py` (mới) | Đọc tên file recording → mã TC + giờ; chọn booking khớp |
| `obeval/store.py` (mới) | Mọi SQL tới DB đặt lịch qua role `obeval_writer` |
| `obeval/gcs.py` (mới) | Đường dẫn và tải transcript onboarding từ GCS |
| `obeval/transcribe_client.py` (mới) | Gọi temp-transcript `/beta/transcript` |
| `obeval/tasks.py` (mới) | Tạo Cloud Task gọi lại `/v1/tasks/advance` |
| `obeval/service.py` (mới) | Điều phối `register` / `advance`; phụ thuộc bơm qua `Deps` |
| `obeval/app.py` (mới) | FastAPI: `/healthz`, `/v1/recordings`, `/v1/tasks/advance` |
| `obeval/db.py` (sửa) | Bỏ REST + service key; `push` ghi qua `Store` |
| `obeval/cli.py` (sửa) | Lệnh `repeat` (đo dao động), `publish`; `push-db` dùng `Store` |
| `obeval/compare.py` (sửa) | Hàm `stability` cho cổng ±5 điểm |
| `obeval/config.py` (sửa) | `PUBLISH` |
| `sql/003_obeval_writer.sql` (mới) | Cột điều phối, bảng file không khớp, role `obeval_writer`, RLS |
| `tools/apps_script/onboarding.gs` (mới) | Bản lưu nhánh onboarding thêm vào script đồng bộ recording |
| `Dockerfile`, `.dockerignore`, `requirements.txt` | Đóng gói Cloud Run |
| `tests/test_recording.py`, `tests/test_service.py`, `tests/test_adapters.py` (mới) | Test |

`temp-transcript` (nhánh `tanh/feat/onboarding-profile` từ `main`): `app/stt_request.py` (mới), `app/pipeline.py`, `main.py`, `tests/test_stt_request.py` (mới).

`SpeechToText` (nhánh `tanh/feat/onboarding-profile` từ **`origin/nah/feat/stt-v1-primary`** — đây là bản đang chạy prod, chưa merge vào `main`): `api-go/cmd/api/main.go`, `app/config.py`, `app/worker.py`, `tests/test_worker.py`.

`TeenCareBooking` (nhánh `tanh/dev/onboarding-ai-report`): `supabase/migrations/*_onboarding_*.sql`.

---

### Task 0: Chuẩn bị nhánh và môi trường

**Files:** không đổi code.

- [ ] **Step 1: Hỏi anh Tuấn Anh** có đồng ý commit các thay đổi đang dở trong `pdc-onboarding-eval` (STT, email có mốc giờ, dashboard, `db.py`, `sql/`, tests) lên nhánh mới không. Chưa đồng ý thì dừng.

- [ ] **Step 2: Tạo nhánh và commit hiện trạng**

```bash
cd d:/TeenCare/pdc-onboarding-eval
git switch -c feat/onboarding-service
git status --short          # kiểm: không có gì trong data/, không có file key
git add HANDOFF.md README.md obeval tests sql tools docs
git commit -m "feat: STT chia người nói, báo cáo Mentor, schema DB kết quả chấm"
```

- [ ] **Step 3: Cài thư viện và chạy test nền**

```bash
python -m pip install "fastapi>=0.115" "uvicorn>=0.30" "psycopg[binary]>=3.2" "google-cloud-storage>=2.18" "google-cloud-tasks>=2.16"
python -m unittest discover -s tests
```
Expected: `OK` (66 test).

---

### Task 1: Cập nhật tài liệu kế hoạch theo 5 thay đổi

**Files:**
- Modify: `docs/ke-hoach-trien-khai.md`

- [ ] **Step 1: Thay khối luồng ở mục 3.3** bằng:

```
Recording onboarding (Drive)
  → Apps Script: nhận tên "…1_1 Onboarding…" → chuyển sang folder Onboarding riêng → gọi obeval
  → obeval [Cloud Run]  POST /v1/recordings
       mã TC + giờ trong tên file → tìm booking onboarding trong DB đặt lịch → booking_id
  → obeval gọi temp-transcript  /beta/transcript  {session_id = booking_id, profile = "onboarding"}
  → STT: job onboarding luôn chạy pipeline chia người nói
       → gs://teenup-transcripts/transcripts/onboarding/<booking_id>.json   (xoá sau 90 ngày)
  → obeval hỏi lại 5 phút/lần qua Cloud Tasks (tối đa 3 giờ) → đọc JSON → chấm
  → ghi DB đặt lịch bằng role obeval_writer (điểm cuối của pipeline)

DB đặt lịch ──► báo cáo Mentor trong TeenCareBooking (chỉ khi published_at có giá trị)
           └─► dashboard PDC (Data Analyst dựng, đọc thẳng DB)
```

- [ ] **Step 2: Bước 2** — xoá mục 2.1 (session-on-trigger) và 2.2 (session-data-worker); thêm một dòng đầu Bước 2: "Không đi qua session-on-trigger và session-data-worker: obeval tự ghép booking và tự gọi temp-transcript (ít sửa service prod, không phụ thuộc lịch Nhật Anh)." Ở 2.3 và 2.4 thay `transcripts/<booking_id>.json` bằng `transcripts/onboarding/<booking_id>.json`.

- [ ] **Step 3: Bước 3** — thêm 3 dòng vào bảng: "Quyền GCS: chỉ đọc `transcripts/onboarding/` (IAM condition); lifecycle xoá sau 90 ngày", "DB: role `obeval_writer` chỉ đọc 6 cột `bookings` và ghi 5 bảng kết quả, không dùng service-role key; RLS bật cho mọi bảng mới, Mentor chỉ thấy buổi của mình", "Ngưỡng đạt: PDC chốt, đặt bằng `OBEVAL_GOOD_THRESHOLD` (hiện tạm 80%)".

- [ ] **Step 4: Thêm mục "Cổng chất lượng trước khi Mentor thấy kết quả"** ngay trước "Lộ trình":

```markdown
## Cổng chất lượng trước khi Mentor thấy kết quả

`published_at` để trống (Mentor không thấy gì) cho tới khi đạt cả 3 điều kiện:
1. 5 buổi onboarding thật được PDC chấm tay.
2. Đạt 5 chỉ tiêu nghiệm thu trên 5 buổi đó: trùng phân loại ≥ 85%, lệch tỷ lệ toàn ca ≤ 5 điểm %, tìm đúng lỗi ≥ 85%, logic liên kết ≥ 80%, NF có dẫn chứng 100%.
3. Chấm lại cùng một buổi 3 lần, % follow lệch ≤ 5 điểm % (hiện đo được 11 điểm trên một ca — phải giảm trước).
Bắt đầu ngay tuần 1, song song với việc xây pipeline. Qua cổng thì chạy `python run.py publish` và đặt `OBEVAL_PUBLISH=true`.
```

- [ ] **Step 5: Lộ trình** — tuần 1 thêm "Cổng chất lượng: xin 5 buổi PDC chấm tay, đo dao động"; tuần 4 đổi thành "Bật hiển thị cho Mentor — chỉ khi qua cổng chất lượng". Mục "Cần sếp quyết": thay ý ngưỡng bằng "Ngưỡng đạt do PDC chốt (hiện tạm 80%)".

- [ ] **Step 6: Commit**

```bash
git add docs/ke-hoach-trien-khai.md
git commit -m "docs: kế hoạch triển khai theo 5 thay đổi đã duyệt"
```

---

### Task 2: Đọc tên file recording và chọn booking

**Files:**
- Create: `obeval/recording.py`
- Test: `tests/test_recording.py`

**Interfaces:**
- Produces: `recording.VN: timezone`; `recording.RecordingName(student_code: str, recorded_at: datetime)`; `recording.is_onboarding(name: str) -> bool`; `recording.parse(name: str) -> RecordingName | None`; `recording.pick_booking(rows: list[dict], recorded_at: datetime, window: timedelta = WINDOW) -> dict | None` (mỗi row có `start_at` là datetime có múi giờ, `status`).

- [ ] **Step 1: Viết test**

```python
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

    def test_other_timezone(self):
        r = recording.parse(NAME.replace("GMT+07_00", "GMT+08_00"))
        self.assertEqual(r.recorded_at.astimezone(timezone.utc), datetime(2026, 10, 11, 12, 29, tzinfo=timezone.utc))

    def test_missing_timezone_means_vietnam(self):
        r = recording.parse(NAME.replace(" GMT+07_00", ""))
        self.assertEqual(r.recorded_at, datetime(2026, 10, 11, 20, 29, tzinfo=recording.VN))

    def test_unicode_variants(self):
        name = NAME.replace(" ", "\u00a0").replace("20_29", "20：29").replace("–", "\u2014")
        r = recording.parse(name)
        self.assertEqual((r.student_code, r.recorded_at.hour, r.recorded_at.minute), ("TC99999", 20, 29))

    def test_unparsable(self):
        self.assertIsNone(recording.parse("Recording.mp4"))
        self.assertIsNone(recording.parse(NAME.replace("TC99999", "HS99999")))
        self.assertIsNone(recording.parse(NAME.replace("2026_10_11", "2026_13_45")))

    def test_is_onboarding(self):
        self.assertTrue(recording.is_onboarding(NAME))
        self.assertFalse(recording.is_onboarding(NAME.replace("1_1 Onboarding", "Mentor 1_1 hàng tuần")))


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
```

- [ ] **Step 2: Chạy để thấy lỗi**

Run: `python -m unittest tests.test_recording -v`
Expected: FAIL `ImportError: cannot import name 'recording'`

- [ ] **Step 3: Viết `obeval/recording.py`**

```python
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
ONBOARDING_MARK = "1_1 onboarding"
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
    for a, b in (("\u2013", "-"), ("\u2014", "-"), ("\u00a0", " "), ("\u202f", " ")):
        s = s.replace(a, b)
    return s.strip()


def is_onboarding(name: str) -> bool:
    return ONBOARDING_MARK in _normalize(name).lower()


def parse(name: str) -> RecordingName | None:
    s = _normalize(name)
    tc, dt = _TC.search(s), _DT.search(s)
    if not tc or not dt:
        return None
    y, mo, d, h, mi = (int(x) for x in dt.groups())
    tz = VN  # tên không ghi múi giờ → giờ Việt Nam, như session-on-trigger
    m = _TZ.search(s, dt.end())
    if m:
        sign = 1 if m.group(1) == "+" else -1
        tz = timezone(sign * timedelta(hours=int(m.group(2)), minutes=int(m.group(3) or 0)))
    try:
        at = datetime(y, mo, d, h, mi, tzinfo=tz)
    except ValueError:
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
```

- [ ] **Step 4: Chạy test**

Run: `python -m unittest tests.test_recording -v`
Expected: 9 test PASS

- [ ] **Step 5: Commit**

```bash
git add obeval/recording.py tests/test_recording.py
git commit -m "feat(service): đọc tên file recording onboarding và chọn booking khớp"
```

---

### Task 3: Công cụ đo dao động điểm (`repeat`) cho cổng ±5 điểm

**Files:**
- Modify: `obeval/compare.py` (thêm hàm cuối file)
- Modify: `obeval/cli.py` (lệnh `repeat`)
- Test: `tests/test_obeval.py` (thêm vào `TestCompare`)

**Interfaces:**
- Produces: `compare.stability(overalls: list[float | None], limit_pp: float = 5.0) -> dict` với khoá `runs, min, max, spread_pp, pass`; lệnh `python run.py repeat <transcript> --times N`.

- [ ] **Step 1: Viết test** (thêm vào class `TestCompare`)

```python
    def test_stability_gate(self):
        bad = compare.stability([0.650, 0.618, 0.728])
        self.assertEqual((bad["spread_pp"], bad["pass"]), (11.0, False))
        good = compare.stability([0.70, 0.72, 0.73])
        self.assertEqual((good["spread_pp"], good["pass"]), (3.0, True))
        one = compare.stability([0.70, None])
        self.assertEqual((one["runs"], one["spread_pp"], one["pass"]), (1, None, False))
```

- [ ] **Step 2: Chạy để thấy lỗi**

Run: `python -m unittest tests.test_obeval.TestCompare.test_stability_gate -v`
Expected: FAIL `AttributeError: module 'obeval.compare' has no attribute 'stability'`

- [ ] **Step 3: Thêm vào cuối `obeval/compare.py`**

```python
def stability(overalls: list[float | None], limit_pp: float = 5.0) -> dict:
    """Cổng chất lượng: chấm lại cùng một buổi, % follow lệch (max − min) không quá limit_pp điểm %."""
    vals = [v for v in overalls if v is not None]
    if len(vals) < 2:
        return {"runs": len(vals), "min": None, "max": None, "spread_pp": None, "pass": False}
    spread = round((max(vals) - min(vals)) * 100, 1)
    return {"runs": len(vals), "min": min(vals), "max": max(vals), "spread_pp": spread, "pass": spread <= limit_pp}
```

- [ ] **Step 4: Thêm lệnh vào `obeval/cli.py`** — hàm đặt sau `cmd_template`:

```python
def cmd_repeat(args) -> int:
    tp = Path(args.transcript)
    key = pipeline.case_key_from(tp, args.session_date)
    overalls = []
    for k in range(args.times):
        meta = {**_meta(args), "case_id": f"{key}-lap{k + 1}"}
        res = pipeline.run_case(tp, meta, model=args.model, thinking_budget=args.thinking,
                                out_root=Path(args.out_root), fmt=args.format, runs=args.runs)
        overalls.append(res.get("overall"))
        print(f"Lần {k + 1}/{args.times}: {res['state']} · {res.get('overall')}")
    rep = cmp_mod.stability(overalls)
    _print(rep)
    return 0 if rep["pass"] else 1
```

và trong `main()` sau khối `human-template`:

```python
    p = sub.add_parser("repeat", help="Chấm lại cùng một transcript nhiều lần, đo độ lệch % follow (cổng ≤ 5 điểm)")
    p.add_argument("transcript")
    p.add_argument("--times", type=int, default=3)
    common(p)
    p.set_defaults(func=cmd_repeat)
```

Sửa docstring dòng 1 của `cli.py` thành `"""Lệnh: run · batch · rescore · dashboard · compare · human-template · repeat · push-db · publish · check-vertex."""`.

- [ ] **Step 5: Chạy toàn bộ test**

Run: `python -m unittest discover -s tests`
Expected: OK

- [ ] **Step 6: Commit**

```bash
git add obeval/compare.py obeval/cli.py tests/test_obeval.py
git commit -m "feat(gate): lệnh repeat đo dao động % follow khi chấm lại cùng một buổi"
```

---

### Task 4: Chạy cổng chất lượng (song song từ tuần 1)

Việc vận hành, không phải code. Kết quả ghi vào `docs/nghiem-thu.md` (chỉ số liệu, không chép lời gia đình).

**Files:**
- Create: `docs/nghiem-thu.md`

- [ ] **Step 1: Tạo phiếu chấm tay và gửi PDC 5 buổi**

```bash
python run.py human-template data/nghiem-thu/phieu-trong.csv
```
Gửi PDC phiếu trống + 5 recording onboarding (chọn 5 buổi khác Mentor). PDC trả 5 file `data/nghiem-thu/<ma-ca>.csv`.

- [ ] **Step 2: Chép lời 5 buổi bằng STT trên máy** (cho tới khi pipeline tự động chạy)

```bash
D:/TeenCare/SpeechToText-diarized/.venv-dev/Scripts/python tools/stt_local.py "<video.mp4>" data/nghiem-thu/in/<ma-ca>.json \
  --dll-dir D:/TeenCare/SpeechToText/poc/.venv/Lib/site-packages/nvidia/cublas/bin \
  --dll-dir D:/TeenCare/SpeechToText/poc/.venv/Lib/site-packages/nvidia/cudnn/bin
```
Xoá video gốc khỏi máy ngay sau khi có JSON.

- [ ] **Step 3: Chấm và đối chiếu**

```bash
python run.py batch data/nghiem-thu/in --out-root data/nghiem-thu/out
# pairs.txt: mỗi dòng "data/nghiem-thu/out/<case_dir>,data/nghiem-thu/<ma-ca>.csv"
python run.py compare --pairs data/nghiem-thu/pairs.txt --out data/nghiem-thu/compare.md
```
Expected: bảng 5 chỉ tiêu cho từng ca và tổng.

- [ ] **Step 4: Đo dao động trên cả 5 buổi**

```bash
python run.py repeat data/nghiem-thu/in/<ma-ca>.json --times 3 --out-root data/nghiem-thu/repeat
```
Expected: dòng `"pass": true` khi lệch ≤ 5 điểm. Chi phí ≈ 3 × 0,6 USD / buổi.

- [ ] **Step 5: Nếu dao động > 5 điểm** — đo lại với 5 lần chấm mỗi lượt:

```bash
python run.py repeat data/nghiem-thu/in/<ma-ca>.json --times 3 --runs 5 --out-root data/nghiem-thu/repeat-r5
```
Đạt thì đặt `OBEVAL_RUNS=5` cho Cloud Run ở Task 11 (chi phí mỗi ca tăng khoảng 5/3). Vẫn không đạt thì dừng, ghi các tiêu chí hay đổi trạng thái giữa các lần vào `docs/nghiem-thu.md` và gửi PDC làm rõ tiêu chí — **không** bật hiển thị cho Mentor.

- [ ] **Step 6: Ghi kết quả** vào `docs/nghiem-thu.md`: bảng 5 chỉ tiêu × 5 ca, dao động từng ca, `OBEVAL_RUNS` đã chọn, ngưỡng đạt PDC chốt (nếu đã có), kết luận đạt / chưa đạt.

- [ ] **Step 7: Commit**

```bash
git add docs/nghiem-thu.md
git commit -m "docs: kết quả cổng chất lượng onboarding"
```

---

### Task 5: Schema điều phối, role `obeval_writer`, RLS

**Files:**
- Create: `sql/003_obeval_writer.sql`
- Modify: `docs/data-cho-dashboard.md` (mục 3.1 thêm 4 cột; thêm mục 3.7 bảng file không khớp; mục 6 ghi "ngưỡng do PDC chốt, hiện tạm 0.80")

- [ ] **Step 1: Viết `sql/003_obeval_writer.sql`**

```sql
-- obeval chạy tự động: cột điều phối, bảng file không khớp, role ghi riêng (không dùng service-role key).
-- Chạy SAU 001 và 002. Dev: anh Tuấn Anh chạy. Prod: chủ DB chạy qua PR vào TeenCareBooking.
-- Mật khẩu role KHÔNG nằm trong file: chạy riêng `alter role obeval_writer password '<giá trị trong Secret Manager>';`

begin;

-- 1. Cột điều phối của một lượt chấm
alter table public.onboarding_evaluations
  add column if not exists recording_file_id text,      -- Drive file id
  add column if not exists recording_url     text,      -- link Drive gửi cho temp-transcript
  add column if not exists run_id            bigint,    -- mỗi lần bắt đầu lại có run_id mới; Cloud Task cũ bị bỏ
  add column if not exists attempts          integer not null default 0;

-- 2. Recording không ghép được booking — chờ xử lý tay (chỉ admin xem; tên file có tên / SĐT phụ huynh)
create table if not exists public.onboarding_recording_unmatched (
  file_id        text        primary key,
  file_name      text        not null,
  reason         text        not null check (reason in ('unparsable_name', 'no_booking')),
  first_seen_at  timestamptz not null default now(),
  last_seen_at   timestamptz not null default now()
);
alter table public.onboarding_recording_unmatched enable row level security;
drop policy if exists onboarding_recording_unmatched_admin_read on public.onboarding_recording_unmatched;
create policy onboarding_recording_unmatched_admin_read on public.onboarding_recording_unmatched
  for select to authenticated using (exists (select 1 from public.admin_users a where a.user_id = auth.uid()));

-- 3. Role riêng của obeval: đăng nhập được, không kế thừa, không bỏ qua RLS
do $$ begin
  if not exists (select 1 from pg_roles where rolname = 'obeval_writer') then
    create role obeval_writer login noinherit nobypassrls;
  end if;
end $$;

grant usage on schema public to obeval_writer;
-- Chỉ 6 cột cần để ghép buổi — không tên / SĐT / email phụ huynh
grant select (id, event_type_id, mentor_id, start_at, status, student_code) on public.bookings to obeval_writer;
grant select (id, name) on public.event_types to obeval_writer;
grant select on public.onboarding_criteria to obeval_writer;
grant select, insert, update on public.onboarding_evaluations to obeval_writer;
grant select, insert, update, delete on public.onboarding_evaluation_steps to obeval_writer;
grant select, insert, update on public.onboarding_evaluation_audit to obeval_writer;
grant select, insert, update on public.onboarding_recording_unmatched to obeval_writer;

-- 4. RLS cho role này (Mentor / admin giữ nguyên policy ở 001)
drop policy if exists obeval_writer_bookings on public.bookings;
create policy obeval_writer_bookings on public.bookings for select to obeval_writer
  using (event_type_id in (select id from public.event_types where name = 'Gia sư tâm lý 1:1 Onboarding'));
drop policy if exists obeval_writer_event_types on public.event_types;
create policy obeval_writer_event_types on public.event_types for select to obeval_writer using (true);
drop policy if exists obeval_writer_criteria on public.onboarding_criteria;
create policy obeval_writer_criteria on public.onboarding_criteria for select to obeval_writer using (true);
drop policy if exists obeval_writer_evaluations on public.onboarding_evaluations;
create policy obeval_writer_evaluations on public.onboarding_evaluations for all to obeval_writer using (true) with check (true);
drop policy if exists obeval_writer_steps on public.onboarding_evaluation_steps;
create policy obeval_writer_steps on public.onboarding_evaluation_steps for all to obeval_writer using (true) with check (true);
drop policy if exists obeval_writer_audit on public.onboarding_evaluation_audit;
create policy obeval_writer_audit on public.onboarding_evaluation_audit for all to obeval_writer using (true) with check (true);
drop policy if exists obeval_writer_unmatched on public.onboarding_recording_unmatched;
create policy obeval_writer_unmatched on public.onboarding_recording_unmatched for all to obeval_writer using (true) with check (true);

commit;

-- Hoàn tác (chỉ DEV):
-- drop policy if exists obeval_writer_bookings on public.bookings; drop policy if exists obeval_writer_event_types on public.event_types;
-- drop table if exists public.onboarding_recording_unmatched;
-- alter table public.onboarding_evaluations drop column if exists recording_file_id, drop column if exists recording_url,
--   drop column if exists run_id, drop column if exists attempts;
-- revoke all on all tables in schema public from obeval_writer; revoke usage on schema public from obeval_writer; drop role obeval_writer;
```

- [ ] **Step 2: Kiểm cú pháp bằng parser** (không chạy lên DB)

```bash
python -m pip install pglast
python -c "import pglast,sys; print(len(pglast.parse_sql(open('sql/003_obeval_writer.sql',encoding='utf-8').read())), 'lệnh')"
```
Expected: in ra số lệnh, không lỗi.

- [ ] **Step 3: Anh Tuấn Anh chạy trên DB dev** `ktazdnmmpudgvewkbgaq` (SQL Editor), rồi chạy riêng `alter role obeval_writer password '…';` với mật khẩu mới sinh (`python -c "import secrets;print(secrets.token_urlsafe(32))"`), lưu mật khẩu vào Secret Manager ở Task 11, không lưu vào file.

- [ ] **Step 4: Kiểm quyền trên dev** bằng chính role đó (DSN lấy từ Supabase → Connect → Session pooler, user `obeval_writer.ktazdnmmpudgvewkbgaq`):

```bash
psql "$OBEVAL_DB_DSN" -c "select count(*) from public.bookings"                 # chạy được, chỉ đếm buổi onboarding
psql "$OBEVAL_DB_DSN" -c "select parent_name from public.bookings limit 1"      # PHẢI lỗi: permission denied
psql "$OBEVAL_DB_DSN" -c "select count(*) from public.mentors"                  # PHẢI lỗi: permission denied
```

- [ ] **Step 5: Sửa `docs/data-cho-dashboard.md`** như mô tả ở mục Files.

- [ ] **Step 6: Commit**

```bash
git add sql/003_obeval_writer.sql docs/data-cho-dashboard.md
git commit -m "feat(db): role obeval_writer, RLS và cột điều phối cho obeval tự động"
```

---

### Task 6: `Store` — DB đặt lịch qua `obeval_writer`; `push-db` và `publish`

**Files:**
- Create: `obeval/store.py`
- Modify: `obeval/db.py` (bỏ `Rest`, `push` cũ; thêm `push` mới), `obeval/cli.py` (`push-db`, `publish`)
- Test: `tests/test_obeval.py` (thêm vào `TestDbRows`)

**Interfaces:**
- Consumes: `recording.VN` (Task 2); `db.build_rows(doc, booking_id, names, *, publish)` (có sẵn).
- Produces: class `store.Store(dsn: str | None = None)` với:
  - `booking_candidates(student_code: str, around: datetime, days: int = 2) -> list[dict]` (khoá `id: str, start_at: datetime, status: str, mentor_id: str`)
  - `evaluation(booking_id: str) -> dict | None` (khoá `booking_id, status, updated_at, recording_file_id, recording_url, run_id, attempts, session_date`)
  - `start(booking: dict, file: dict) -> int` (trả `run_id`)
  - `touch(booking_id: str, attempts: int) -> None`
  - `fail(booking_id: str, status: str, error: str) -> None` (`status` ∈ `error`, `insufficient`)
  - `save_result(rows: dict) -> None` (`rows` = kết quả `db.build_rows`)
  - `record_unmatched(file: dict, reason: str) -> None`
  - `publish_done() -> int`
  - `db.push(case_dir: Path, booking_id: str, store, *, publish: bool = False) -> dict`

- [ ] **Step 1: Viết test cho `db.push`** (thêm vào `TestDbRows`)

```python
    def test_push_goes_through_store(self):
        from obeval import db

        class FakeStore:
            saved = None

            def save_result(self, rows):
                FakeStore.saved = rows

        res, _ = validate.normalize(fake_raw())
        sc = score.compute(res, CRIT, good_threshold=0.80)
        doc = {"meta": {"session_date": "2026-10-11"}, "scores": sc, "run": {"model": "m"}, **res}
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "result.json").write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
            out = db.push(Path(d), "b-1", FakeStore(), publish=False)
        self.assertEqual((out["booking_id"], out["steps"], out["published"]), ("b-1", 37, False))
        self.assertEqual(FakeStore.saved["evaluation"]["booking_id"], "b-1")
        self.assertFalse(hasattr(db, "Rest"))  # không còn đường ghi bằng service key
```

- [ ] **Step 2: Chạy để thấy lỗi**

Run: `python -m unittest tests.test_obeval.TestDbRows -v`
Expected: FAIL (`push()` sai chữ ký / `Rest` vẫn còn)

- [ ] **Step 3: Sửa `obeval/db.py`** — xoá import `os`, `urllib.error`, `urllib.request`, `datetime` không dùng tới ngoài `build_rows` (giữ `datetime, timezone` vì `build_rows` dùng); xoá class `Rest` và hàm `push` cũ; sửa docstring đầu file thành:

```python
"""Dựng các dòng ghi DB đặt lịch (bảng onboarding_evaluations*, xem sql/001 và sql/003) từ result.json.

Ghi thật đi qua `store.Store` (role `obeval_writer`, OBEVAL_DB_DSN) — không dùng service-role key.
`mentor_report` là bản NGẮN cho Mentor xem trong TeenCareBooking; bản đầy đủ có trích dẫn nằm ở bảng audit (chỉ admin).
"""
```

và thêm vào cuối file:

```python
def push(case_dir: Path, booking_id: str, store, *, publish: bool = False) -> dict:
    """Ghi một ca đã chấm (thư mục có result.json) cho booking_id."""
    doc = json.loads((Path(case_dir) / "result.json").read_text(encoding="utf-8"))
    rows = build_rows(doc, booking_id, Names(prompt.load_criteria()), publish=publish)
    store.save_result(rows)
    return {"booking_id": booking_id, "status": rows["evaluation"]["status"],
            "overall": rows["evaluation"]["overall"], "steps": len(rows["steps"]), "published": publish}
```

- [ ] **Step 4: Viết `obeval/store.py`**

```python
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
               "run_id": run_id, "attempts": 0}
        with self._conn() as c:
            _upsert(c.cursor(), "onboarding_evaluations", row, ("booking_id",))
        return run_id

    def touch(self, booking_id: str, attempts: int) -> None:
        with self._conn() as c:
            c.execute("update public.onboarding_evaluations set attempts = %s where booking_id = %s",
                      (attempts, booking_id))

    def fail(self, booking_id: str, status: str, error: str) -> None:
        with self._conn() as c:
            c.execute("update public.onboarding_evaluations set status = %s, error = %s where booking_id = %s",
                      (status, error[:1000], booking_id))

    def save_result(self, rows: dict) -> None:
        """evaluation + 37 steps + audit trong MỘT transaction (chấm lại thì thay cả 37 dòng)."""
        ev = rows["evaluation"]
        with self._conn() as c, c.cursor() as cur:
            _upsert(cur, "onboarding_evaluations", ev, ("booking_id",))
            cur.execute("delete from public.onboarding_evaluation_steps where booking_id = %s", (ev["booking_id"],))
            cur.executemany(
                "insert into public.onboarding_evaluation_steps (booking_id, criterion_id, activity, status) "
                "values (%s, %s, %s, %s)",
                [(s["booking_id"], s["criterion_id"], s["activity"], s["status"]) for s in rows["steps"]])
            _upsert(cur, "onboarding_evaluation_audit", rows["audit"], ("booking_id",))

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
```

- [ ] **Step 5: Sửa `obeval/cli.py`** — thay `cmd_push_db` và parser `push-db`, thêm `publish`:

```python
def cmd_push_db(args) -> int:
    from . import db
    from .store import Store
    _print(db.push(Path(args.case_dir), args.booking_id, Store(), publish=args.publish))
    return 0


def cmd_publish(args) -> int:
    from .store import Store
    print(f"Đã cho Mentor xem {Store().publish_done()} ca")
    return 0
```

```python
    p = sub.add_parser("push-db", help="Ghi kết quả một ca lên DB đặt lịch (OBEVAL_DB_DSN, role obeval_writer)")
    p.add_argument("case_dir")
    p.add_argument("--booking-id", required=True, help="bookings.id của buổi onboarding")
    p.add_argument("--publish", action="store_true", help="Cho Mentor xem ngay (chỉ sau khi qua cổng chất lượng)")
    p.set_defaults(func=cmd_push_db)

    p = sub.add_parser("publish", help="Qua cổng chất lượng: cho Mentor xem mọi ca đã chấm xong")
    p.set_defaults(func=cmd_publish)
```

- [ ] **Step 6: Chạy toàn bộ test**

Run: `python -m unittest discover -s tests`
Expected: OK

- [ ] **Step 7: Kiểm trên DB dev** (cần anh Tuấn Anh đồng ý ghi dev; dùng booking giả đã tạo hôm 12/10):

```bash
set OBEVAL_DB_DSN=<DSN dev của obeval_writer>
python run.py push-db data/out/2026-10-11_2026-10-11_TC23059_1e0fc0 --booking-id <booking giả trên dev>
```
Expected: in `"steps": 37`; trên dev `onboarding_evaluations.published_at` là null.

- [ ] **Step 8: Commit**

```bash
git add obeval/store.py obeval/db.py obeval/cli.py tests/test_obeval.py
git commit -m "feat(db): ghi DB qua role obeval_writer, bỏ service key; lệnh publish"
```

---

### Task 7: Điều phối `register` / `advance` (+ GCS, temp-transcript, Cloud Tasks)

**Files:**
- Create: `obeval/service.py`, `obeval/gcs.py`, `obeval/transcribe_client.py`, `obeval/tasks.py`
- Test: `tests/test_service.py`, `tests/test_adapters.py`

**Interfaces:**
- Consumes: `recording.is_onboarding / parse / pick_booking` (Task 2); `Store` methods (Task 6); `db.build_rows`; `pipeline.run_case(path, meta, out_root=...)`; `transcript.load(path)` → `Transcript.source_format` (`"stt_diarized"` khi STT có vai).
- Produces:
  - `gcs.transcript_uri(booking_id: str) -> str`; `gcs.download(uri: str, dest: Path) -> bool`
  - `transcribe_client.request(booking_id: str, recording_url: str, opener=urllib.request.urlopen) -> str` (`processing|done|error`; ném `service.TransientError` khi 5xx / mạng)
  - `tasks.build_task(parent, self_url, token, booking_id, run_id, attempt, delay_sec, now) -> dict`; `tasks.enqueue_advance(booking_id: str, run_id: int, attempt: int, delay_sec: int) -> None`
  - `service.TransientError`, `service.Deps`, `service.register(file: dict, deps) -> dict`, `service.advance(booking_id: str, run_id: int, attempt: int, deps) -> dict`, `service.token_ok(given: str | None, expected: str | None) -> bool`, hằng `POLL_DELAY_SEC = 300`, `MAX_ATTEMPTS = 36`

- [ ] **Step 1: Viết `tests/test_service.py`**

```python
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

    def touch(self, bid, attempts):
        self.ev["attempts"] = attempts

    def fail(self, bid, status, error):
        self.ev.update(status=status, error=error)

    def save_result(self, rows):
        self.saved = rows
        self.ev["status"] = rows["evaluation"]["status"]

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
        self.assertEqual((st.starts, self.enqueued), (1, [("b-1", 7, 0, 0)]))

    def test_restarts_stale_processing(self):
        st = FakeStore(ev={"status": "processing", "recording_file_id": "file-1", "run_id": 3,
                           "updated_at": NOW - timedelta(hours=1)})
        self.assertEqual(service.register(FILE, self.deps(st))["status"], "queued")

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
        self.assertIn(out["status"], ("done", "insufficient"))
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
        self.eval_result = {"state": "error", "error": "Transcript rỗng — không chấm"}
        self.assertEqual(service.advance("b-1", 7, 1, self.deps(st))["status"], "error")


class TestToken(unittest.TestCase):
    def test_token_ok(self):
        self.assertTrue(service.token_ok("abc", "abc"))
        self.assertFalse(service.token_ok("abd", "abc"))
        self.assertFalse(service.token_ok(None, "abc"))
        self.assertFalse(service.token_ok("", ""))  # chưa cấu hình token thì từ chối hết


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Viết `tests/test_adapters.py`**

```python
"""Lớp nối ra ngoài: đường dẫn GCS, phân loại lỗi temp-transcript, dựng Cloud Task — không gọi mạng."""
from __future__ import annotations

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


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: Chạy để thấy lỗi**

Run: `python -m unittest tests.test_service tests.test_adapters -v`
Expected: FAIL `ImportError` (chưa có `service`, `gcs`, `tasks`, `transcribe_client`)

- [ ] **Step 4: Viết `obeval/gcs.py`**

```python
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
```

- [ ] **Step 5: Viết `obeval/transcribe_client.py`**

```python
"""Gọi temp-transcript: tải recording Drive → mp3 → gửi STT với profile=onboarding.

Lần đầu temp-transcript stream cả video sang mp3 ngay trong request (vài phút với file > 1 GB),
nên timeout dài. Gọi lại cùng booking_id thì nó trả trạng thái job đã có.
"""
from __future__ import annotations

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
    except (urllib.error.URLError, TimeoutError) as exc:
        raise TransientError(str(exc)) from None
```

- [ ] **Step 6: Viết `obeval/tasks.py`**

```python
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
    task = build_task(parent, os.environ["OBEVAL_SELF_URL"], os.environ["OBEVAL_API_TOKEN"],
                      booking_id, run_id, attempt, delay_sec, datetime.now(timezone.utc))
    task["http_request"]["http_method"] = tasks_v2.HttpMethod.POST
    try:
        client.create_task(parent=parent, task=task)
    except AlreadyExists:
        pass
```

- [ ] **Step 7: Viết `obeval/service.py`**

```python
"""Điều phối một ca onboarding: recording Drive → booking → STT (qua temp-transcript) → chấm → DB.

Apps Script gọi `register` một lần cho mỗi file. Phần còn lại chạy qua Cloud Tasks gọi `advance`
5 phút/lần cho tới khi STT xong (tối đa 3 giờ — giờ cao điểm STT 20h–22h trùng giờ có onboarding),
rồi chấm ngay trong lượt đó. Mọi phụ thuộc ngoài đi qua `Deps` để test bằng đồ giả.
"""
from __future__ import annotations

import hmac
import json
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

from . import db, gcs, prompt, recording, report, transcript

POLL_DELAY_SEC = 300
MAX_ATTEMPTS = 36
STALE_AFTER = timedelta(minutes=30)
TRANSIENT_MARKERS = ("429", "RESOURCE_EXHAUSTED", "503", "UNAVAILABLE", "DEADLINE_EXCEEDED", "timed out")


class TransientError(RuntimeError):
    """Lỗi tạm (mạng, 5xx, quota) — thử lại ở lượt sau."""


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class Deps:
    store: object
    request_transcript: Callable[[str, str], str]
    download: Callable[[str, Path], bool]
    enqueue: Callable[[str, int, int, int], None]
    evaluate: Callable[[Path, dict, Path], dict]
    publish: bool = False
    now: Callable[[], datetime] = field(default=_utcnow)


def token_ok(given: str | None, expected: str | None) -> bool:
    return bool(expected) and hmac.compare_digest((given or "").encode(), expected.encode())


def register(file: dict, deps: Deps) -> dict:
    name = file.get("name") or ""
    if not recording.is_onboarding(name):
        return {"status": "ignored", "reason": "not_onboarding"}
    parsed = recording.parse(name)
    if parsed is None:
        deps.store.record_unmatched(file, "unparsable_name")
        return {"status": "unmatched", "reason": "unparsable_name"}
    rows = deps.store.booking_candidates(parsed.student_code, parsed.recorded_at)
    booking = recording.pick_booking(rows, parsed.recorded_at)
    if booking is None:
        deps.store.record_unmatched(file, "no_booking")
        return {"status": "unmatched", "reason": "no_booking"}
    bid = booking["id"]
    ev = deps.store.evaluation(bid)
    same_file = bool(ev) and ev.get("recording_file_id") == file["id"]
    if same_file and ev["status"] in ("done", "insufficient"):
        return {"status": "already_done", "booking_id": bid}
    if same_file and ev["status"] == "processing" and deps.now() - ev["updated_at"] < STALE_AFTER:
        return {"status": "in_progress", "booking_id": bid}
    run_id = deps.store.start(booking, file)
    deps.enqueue(bid, run_id, 0, 0)
    return {"status": "queued", "booking_id": bid}


def advance(booking_id: str, run_id: int, attempt: int, deps: Deps) -> dict:
    ev = deps.store.evaluation(booking_id)
    if not ev or ev.get("run_id") != run_id or ev["status"] != "processing":
        return {"status": "stale"}
    try:
        state = deps.request_transcript(booking_id, ev["recording_url"])
    except TransientError:
        state = "processing"
    except Exception as exc:  # noqa: BLE001 — lỗi cố định (4xx): thử lại vô ích
        deps.store.fail(booking_id, "error", f"temp-transcript: {exc}")
        return {"status": "error"}
    if state == "error":
        deps.store.fail(booking_id, "error", "STT báo lỗi khi chép lời")
        return {"status": "error"}
    if state == "done":
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "transcript.json"
            if deps.download(gcs.transcript_uri(booking_id), path):
                return _evaluate(booking_id, run_id, attempt, ev, path, Path(tmp) / "out", deps)
    return _wait(booking_id, run_id, attempt, deps, "STT chưa xong sau 3 giờ")


def _wait(booking_id: str, run_id: int, attempt: int, deps: Deps, timeout_msg: str) -> dict:
    if attempt + 1 >= MAX_ATTEMPTS:
        deps.store.fail(booking_id, "error", timeout_msg)
        return {"status": "error"}
    deps.store.touch(booking_id, attempt + 1)
    deps.enqueue(booking_id, run_id, attempt + 1, POLL_DELAY_SEC)
    return {"status": "waiting", "attempt": attempt + 1}


def _evaluate(booking_id: str, run_id: int, attempt: int, ev: dict, path: Path, out_root: Path, deps: Deps) -> dict:
    tr = transcript.load(path)
    if tr.source_format != "stt_diarized":  # legacy-backlog / legacy-long / legacy-fallback: không có vai
        deps.store.fail(booking_id, "insufficient", "STT trả bản không chia người nói — không chấm")
        return {"status": "insufficient"}
    meta = {"case_id": booking_id, "transcript_source": "stt_diarized"}
    if ev.get("session_date"):
        meta["session_date"] = str(ev["session_date"])
    res = deps.evaluate(path, meta, out_root)
    if res["state"] != "done":
        err = str(res.get("error") or "")
        if any(m in err for m in TRANSIENT_MARKERS):
            return _wait(booking_id, run_id, attempt, deps, f"Chấm lỗi tạm quá số lần thử: {err[:300]}")
        deps.store.fail(booking_id, "error", err[:500])
        return {"status": "error"}
    doc = json.loads((Path(res["case_dir"]) / "result.json").read_text(encoding="utf-8"))
    rows = db.build_rows(doc, booking_id, report.Names(prompt.load_criteria()), publish=deps.publish)
    rows["audit"]["transcript_uri"] = gcs.transcript_uri(booking_id)
    deps.store.save_result(rows)
    return {"status": rows["evaluation"]["status"], "overall": rows["evaluation"]["overall"]}
```

- [ ] **Step 8: Chạy test**

Run: `python -m unittest tests.test_service tests.test_adapters -v`
Expected: PASS hết. Nếu `test_advance_scores_and_saves_unpublished` lỗi vì `transcript.load` không nhận `start_sec`/`role`, đối chiếu khoá với `tests/fixtures/stt_diarized_sample.json` và sửa `stt_json()` cho khớp đúng định dạng file đó (không sửa `transcript.py`).

- [ ] **Step 9: Chạy toàn bộ test**

Run: `python -m unittest discover -s tests`
Expected: OK

- [ ] **Step 10: Commit**

```bash
git add obeval/service.py obeval/gcs.py obeval/transcribe_client.py obeval/tasks.py tests/test_service.py tests/test_adapters.py
git commit -m "feat(service): điều phối recording → STT → chấm → DB qua Cloud Tasks"
```

---

### Task 8: HTTP app, cấu hình và đóng gói Cloud Run

**Files:**
- Create: `obeval/app.py`, `Dockerfile`, `.dockerignore`
- Modify: `obeval/config.py`, `requirements.txt`, `README.md` (mục biến môi trường)

**Interfaces:**
- Consumes: `service.register / advance / token_ok / Deps` (Task 7); `Store` (Task 6); `transcribe_client.request`, `gcs.download`, `tasks.enqueue_advance` (Task 7).
- Produces: `POST /v1/recordings` body `{id, name, webViewLink, createdTime?}`, header `X-Obeval-Token`; `POST /v1/tasks/advance` body `{booking_id, run_id, attempt}`; `GET /healthz`.

- [ ] **Step 1: Thêm vào `obeval/config.py`** (sau `GOOD_THRESHOLD`)

```python
# Cổng chất lượng: false = ghi kết quả nhưng Mentor chưa thấy (published_at trống). Chỉ bật khi qua cổng.
PUBLISH = os.environ.get("OBEVAL_PUBLISH", "false").strip().lower() == "true"
```
và sửa comment của `GOOD_THRESHOLD` thành `# Ngưỡng đạt do PDC chốt (hiện tạm 0.80) — đổi bằng OBEVAL_GOOD_THRESHOLD, không chấm lại.`

- [ ] **Step 2: Viết `obeval/app.py`**

```python
"""HTTP cho Cloud Run: Apps Script báo recording mới; Cloud Tasks gọi lượt tiếp theo.

Cả hai endpoint kiểm header X-Obeval-Token (Secret Manager → OBEVAL_API_TOKEN). Lỗi ngoài dự kiến
trả 500 → Cloud Tasks / Apps Script gọi lại; service.advance tự bỏ qua lượt cũ theo run_id.
"""
from __future__ import annotations

import os
from functools import lru_cache

from fastapi import FastAPI, Header, HTTPException
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


def _require(token: str | None) -> None:
    if not service.token_ok(token, os.environ.get("OBEVAL_API_TOKEN")):
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


@app.post("/v1/recordings")
def recordings(body: RecordingIn, x_obeval_token: str | None = Header(default=None)) -> dict:
    _require(x_obeval_token)
    return service.register(body.model_dump(), _deps())


@app.post("/v1/tasks/advance")
def advance(body: AdvanceIn, x_obeval_token: str | None = Header(default=None)) -> dict:
    _require(x_obeval_token)
    return service.advance(body.booking_id, body.run_id, body.attempt, _deps())
```

- [ ] **Step 3: `requirements.txt`**

```
google-genai>=2.24
jsonschema>=4.23
fastapi>=0.115
uvicorn>=0.30
psycopg[binary]>=3.2
google-cloud-storage>=2.18
google-cloud-tasks>=2.16
```

- [ ] **Step 4: `Dockerfile`**

```dockerfile
FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY obeval/ obeval/
COPY prompt/ prompt/
# Kịch bản PDC KHÔNG nằm trong image: Secret Manager mount vào OBEVAL_SCRIPT lúc chạy.
CMD exec uvicorn obeval.app:app --host 0.0.0.0 --port ${PORT:-8080}
```

- [ ] **Step 5: `.dockerignore`**

```
.git
data/
out/
samples/
tests/
docs/
tools/
**/__pycache__
*.pyc
.env
*.key
*credentials*.json
gcp-key*.json
```

- [ ] **Step 6: Kiểm import và chạy thử local** (không cần GCP)

```bash
python -c "import obeval.app"
set OBEVAL_API_TOKEN=thu
uvicorn obeval.app:app --port 8088
curl -s localhost:8088/healthz
curl -s -o NUL -w "%{http_code}\n" -X POST localhost:8088/v1/recordings -H "Content-Type: application/json" -d "{\"id\":\"x\",\"name\":\"y\",\"webViewLink\":\"z\"}"
```
Expected: `{"status":"ok","service":"obeval"}`; lệnh POST không có token trả `401`.

- [ ] **Step 7: Build image** (cần Docker Desktop)

```bash
docker build -t obeval:local .
docker run --rm obeval:local python -c "import obeval.app, obeval.store; print('ok')"
```
Expected: `ok`; `docker run --rm obeval:local ls /app` không có `data`, `tests`.

- [ ] **Step 8: README** — thêm bảng biến môi trường: `OBEVAL_DB_DSN`, `OBEVAL_API_TOKEN`, `OBEVAL_SCRIPT`, `OBEVAL_TEMP_TRANSCRIPT_URL`, `OBEVAL_TRANSCRIPT_BUCKET`, `OBEVAL_TASKS_PROJECT`, `OBEVAL_TASKS_LOCATION`, `OBEVAL_TASKS_QUEUE`, `OBEVAL_SELF_URL`, `OBEVAL_PUBLISH`, `OBEVAL_GOOD_THRESHOLD` (PDC chốt), `OBEVAL_RUNS`; bỏ dòng `OBEVAL_DB_URL / OBEVAL_DB_KEY`.

- [ ] **Step 9: Chạy toàn bộ test và commit**

```bash
python -m unittest discover -s tests
git add obeval/app.py obeval/config.py requirements.txt Dockerfile .dockerignore README.md
git commit -m "feat(service): endpoint HTTP và Dockerfile cho Cloud Run"
```

---

### Task 9: temp-transcript — tham số `profile`

**Repo:** `d:/TeenCare/temp-transcript`, nhánh `tanh/feat/onboarding-profile` từ `main`.

**Files:**
- Create: `app/stt_request.py`, `tests/test_stt_request.py`
- Modify: `app/pipeline.py` (`enqueue_stt`), `main.py` (`BetaTranscriptRequest`, `beta_transcript`, `_preprocess_and_dispatch`, `_backfill_from_gcs`)

**Interfaces:**
- Produces: request `/beta/transcript` nhận thêm `profile: "" | "onboarding"`; body gửi STT có `profile` khi khác rỗng; job state trên GCS có khoá `profile`.

- [ ] **Step 1: Tạo nhánh**

```bash
cd d:/TeenCare/temp-transcript && git switch main && git pull && git switch -c tanh/feat/onboarding-profile
```

- [ ] **Step 2: Viết test `tests/test_stt_request.py`**

```python
"""Unit tests cho `stt_request` — hồ sơ job và đường dẫn file kết quả STT.

Chạy: `python tests/test_stt_request.py`. Thuần stdlib, không cần GCP.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.stt_request import normalize_profile, stt_body, transcript_object  # noqa: E402


def test_default_profile_keeps_old_path_and_body():
    assert transcript_object("s1", "") == "transcripts/s1.json"
    assert transcript_object("s1", None) == "transcripts/s1.json"
    assert "profile" not in stt_body("gs://b/a.mp3", "s1", "TC1", "https://cb", "vi", "")


def test_onboarding_profile():
    assert transcript_object("b1", "onboarding") == "transcripts/onboarding/b1.json"
    body = stt_body("gs://b/a.mp3", "b1", None, "", "vi", "onboarding")
    assert body == {"gcs_uri": "gs://b/a.mp3", "session_id": "b1", "student_id": "", "callback_url": "",
                    "language": "vi", "profile": "onboarding"}


def test_normalize_profile():
    assert normalize_profile(None) == "" and normalize_profile(" Onboarding ") == "onboarding"
    try:
        normalize_profile("abc")
    except ValueError:
        pass
    else:
        raise AssertionError("profile lạ phải bị từ chối")


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"ok  {name}")
    print("\nTAT CA PASS")
```

- [ ] **Step 3: Chạy để thấy lỗi**

Run: `python tests/test_stt_request.py`
Expected: `ModuleNotFoundError: No module named 'app.stt_request'`

- [ ] **Step 4: Viết `app/stt_request.py`**

```python
"""Tham số gửi STTService và đường dẫn file kết quả theo hồ sơ job.

Hồ sơ "onboarding" (pdc-onboarding-eval gọi): STT luôn chạy pipeline chia người nói và ghi
transcripts/onboarding/<session_id>.json — prefix riêng để chỉ bộ chấm đọc được, xoá sau 90 ngày.
Hồ sơ rỗng = như cũ (buổi 1:1 hàng tuần).
"""
from __future__ import annotations

ONBOARDING = "onboarding"
PROFILES = ("", ONBOARDING)


def normalize_profile(profile: str | None) -> str:
    p = (profile or "").strip().lower()
    if p not in PROFILES:
        raise ValueError(f"profile không hợp lệ: {p!r}")
    return p


def transcript_object(session_id: str, profile: str | None) -> str:
    prefix = "transcripts/onboarding/" if (profile or "") == ONBOARDING else "transcripts/"
    return f"{prefix}{session_id}.json"


def stt_body(mp3_uri: str, session_id: str | None, student_id: str | None, callback_url: str,
             language: str, profile: str | None) -> dict:
    body = {"gcs_uri": mp3_uri, "session_id": session_id or "", "student_id": student_id or "",
            "callback_url": callback_url, "language": language}
    if profile:
        body["profile"] = profile
    return body
```

- [ ] **Step 5: Sửa `app/pipeline.py`** — thêm import `from app.stt_request import stt_body`; đổi chữ ký và phần dựng body của `enqueue_stt`:

```python
def enqueue_stt(mp3_uri: str, session_id: str | None, student_id: str | None,
                lang: str | None = None, profile: str | None = None) -> str:
```
```python
    body = stt_body(mp3_uri, session_id, student_id,
                    f"{SELF_PUBLIC_URL}/beta/transcript/callback" if SELF_PUBLIC_URL else "",
                    whisper_lang(lang), profile)
```
(xoá dict `body = {...}` cũ; phần còn lại giữ nguyên).

- [ ] **Step 6: Sửa `main.py`**
  - import: `from app.stt_request import normalize_profile, transcript_object`
  - `BetaTranscriptRequest` thêm trường (sau `force`):
    ```python
    # Hồ sơ job: "" = như cũ; "onboarding" = STT luôn chia người nói, ghi transcripts/onboarding/.
    profile: str | None = None
    ```
  - đầu `beta_transcript`, sau khối `idempotency_key`:
    ```python
    try:
        profile = normalize_profile(request.profile)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    ```
  - dict `claim` thêm `"profile": profile,`
  - lời gọi cuối: `job = _preprocess_and_dispatch(job_key, source_uri, request.session_id, request.student_id, request.lang, request.force, profile)`
  - `_preprocess_and_dispatch` thêm tham số `profile: str = ""`; trong `job.update({...})` thêm `"profile": profile,`; lời gọi STT: `stt_job_id = pipeline.enqueue_stt(mp3_uri, session_id, student_id, lang, profile)`
  - `_backfill_from_gcs`: thay `uri = f"gs://{GCS_BUCKET_NAME}/transcripts/{sid}.json"` bằng
    ```python
    uri = f"gs://{GCS_BUCKET_NAME}/{transcript_object(sid, job.get('profile'))}"
    ```

- [ ] **Step 7: Chạy mọi test của repo**

```bash
python tests/test_stt_request.py && python tests/test_job_cache.py && python tests/test_transcript_text.py && python tests/test_whisper_lang.py
python -c "import main"
```
Expected: mỗi file in `TAT CA PASS`; import `main` không lỗi.

- [ ] **Step 8: Commit, push, mở PR** (không thêm dòng ghi Claude)

```bash
git add app/stt_request.py app/pipeline.py main.py tests/test_stt_request.py
git commit -m "feat: profile=onboarding — gửi xuống STT và đọc transcripts/onboarding/"
git push -u origin tanh/feat/onboarding-profile
gh pr create --title "feat: profile onboarding cho pdc-onboarding-eval" --body "Thêm tham số profile (mặc định rỗng = không đổi hành vi). profile=onboarding: chuyển xuống STT, backfill đọc transcripts/onboarding/<session_id>.json. STT API bỏ qua trường lạ nên deploy trước hay sau STT đều an toàn."
```

- [ ] **Step 9: Bàn giao deploy** — gửi link PR cho người deploy GCP; ghi vào `docs/deploy-obeval.md` mục "temp-transcript": deploy ngoài 19h–23h, `profile` mặc định rỗng nên không đổi hành vi cũ.

---

### Task 10: STT — job `profile=onboarding`

**Repo:** `d:/TeenCare/SpeechToText` (hoặc worktree `SpeechToText-diarized`), nhánh `tanh/feat/onboarding-profile` từ **`origin/nah/feat/stt-v1-primary`**.

**Files:**
- Modify: `api-go/cmd/api/main.go` (`transcribeReq`, `decodeTranscribeReq`, `enqueue`)
- Modify: `app/config.py` (`onboarding_output_prefix`), `app/worker.py` (`handle_message`, `process_transcribe`)
- Test: `tests/test_worker.py`

**Interfaces:**
- Consumes: body `/v1/transcribe` có `profile` (Task 9).
- Produces: job `profile=onboarding` không rơi về engine cũ khi hàng dồn, không chạy shadow, ghi `transcripts/onboarding/<session_id>.json`.

- [ ] **Step 1: Tạo nhánh**

```bash
cd d:/TeenCare/SpeechToText-diarized && git fetch origin && git switch -c tanh/feat/onboarding-profile origin/nah/feat/stt-v1-primary
```

- [ ] **Step 2: Viết test** (thêm cuối `tests/test_worker.py`)

```python
def test_onboarding_profile_never_drops_to_legacy_on_backlog(monkeypatch):
    monkeypatch.setattr(worker, "settings", replace(worker.settings, pipeline="diarized", diarized_max_backlog=5))
    seen = {}
    monkeypatch.setattr(worker, "process_transcribe", lambda *a, **kw: seen.update(kw))
    r = AckRedis(99)
    worker.handle_message(None, r, "m1", {"job_id": "j1", "session_id": "b1", "input_uri": "gs://in/a.mp3",
                                          "profile": "onboarding"}, FakeEngine())
    assert seen["legacy_only"] is False and seen["allow_shadow"] is False and seen["profile"] == "onboarding"


def test_onboarding_profile_writes_onboarding_prefix(monkeypatch, fake_io):
    monkeypatch.setattr(worker, "settings", replace(worker.settings, pipeline="diarized", delete_input=False,
                                                    onboarding_output_prefix="transcripts/onboarding/"))
    e = FakeEngine()
    worker.process_transcribe(None, e, "j1", "b1", "gs://in/a.mp3", profile="onboarding")
    assert e.calls == ["transcribe"] and fake_io[0][0] == "transcripts/onboarding/"


def test_default_profile_keeps_default_prefix(monkeypatch, fake_io):
    monkeypatch.setattr(worker, "settings", replace(worker.settings, pipeline="diarized", delete_input=False))
    worker.process_transcribe(None, FakeEngine(), "j1", "s1", "gs://in/a.mp3")
    assert fake_io[0][0] is None
```

- [ ] **Step 3: Chạy để thấy lỗi**

Run: `python -m pytest tests/test_worker.py -k "onboarding or default_profile" -v`
Expected: FAIL (`unexpected keyword argument 'profile'` / `onboarding_output_prefix`)

- [ ] **Step 4: `app/config.py`** — thêm cuối class `Settings`:

```python
    onboarding_output_prefix: str = "transcripts/onboarding/"  # job profile=onboarding (pdc-onboarding-eval)
```
và cuối lời gọi `Settings(...)` trong `load_settings()`:

```python
        onboarding_output_prefix=os.environ.get("ONBOARDING_OUTPUT_PREFIX", "transcripts/onboarding/"),
```

- [ ] **Step 5: `app/worker.py`** — thêm hằng sau `EXTRA_KEYS`:

```python
# Job của pdc-onboarding-eval: cần vai người nói để chấm, nên luôn chạy pipeline chia người nói
# (chờ lâu hơn cũng được) và ghi prefix riêng để chỉ bộ chấm đọc được.
ONBOARDING = "onboarding"
```

Trong `handle_message`, sau dòng `language = ...`:

```python
    profile = fields.get("profile") or ""
    onboarding = profile == ONBOARDING
```
và thay hai dòng `allow = ...` / `busy = ...` cùng lời gọi bằng:

```python
        allow = ((lambda: queue_backlog(rdb) <= settings.shadow_max_backlog)
                 if settings.pipeline == "shadow" and not onboarding else False)
        busy = (settings.pipeline == "diarized" and not onboarding
                and queue_backlog(rdb) > settings.diarized_max_backlog)
        process_transcribe(conn, engine, job_id, session_id, input_uri, callback_url, language,
                           allow_shadow=allow, legacy_only=busy, profile=profile)
```

`process_transcribe`: thêm tham số `profile: str = ""` vào cuối chữ ký; đổi `if settings.pipeline == "shadow":` thành `if settings.pipeline == "shadow" and profile != ONBOARDING:`; thay dòng ghi kết quả bằng:

```python
        prefix = settings.onboarding_output_prefix if profile == ONBOARDING else None
        output_uri = storage.upload_transcript(session_id, payload, prefix=prefix) if session_id else None
```

- [ ] **Step 6: Go API** — `transcribeReq` thêm:

```go
	// Hồ sơ job: "" (mặc định, như cũ) | "onboarding" (luôn chia người nói, ghi transcripts/onboarding/).
	Profile string `json:"profile"`
```
`decodeTranscribeReq`, sau dòng `req.StudentID = ...`:

```go
	req.Profile = strings.ToLower(strings.TrimSpace(req.Profile))
	if req.Profile != "" && req.Profile != "onboarding" {
		writeError(w, http.StatusBadRequest, "profile không hợp lệ")
		return req, false
	}
```
`enqueue`, trong `Values`: thêm `"profile": req.Profile,`.

- [ ] **Step 7: Chạy test và build**

```bash
python -m pytest tests -q
cd api-go && go vet ./... && go build ./... ; cd ..
```
Không có Go trên máy thì: `docker build -f api-go/Dockerfile api-go -t stt-api:check`.
Expected: pytest pass hết; Go build không lỗi.

- [ ] **Step 8: Commit, push, PR**

```bash
git add app/config.py app/worker.py tests/test_worker.py api-go/cmd/api/main.go
git commit -m "feat: job profile=onboarding luôn chia người nói, ghi transcripts/onboarding/"
git push -u origin tanh/feat/onboarding-profile
gh pr create --base nah/feat/stt-v1-primary --title "feat: profile onboarding" --body "Job profile=onboarding: không rơi về engine cũ khi hàng dồn, không shadow, ghi transcripts/onboarding/<session_id>.json. Job không có profile giữ nguyên hành vi."
```

- [ ] **Step 9: Anh Tuấn Anh tự deploy lên server GPU** theo quy trình đang dùng (build lại `stt-api` và `stt-worker`, `docker compose up -d`), ngoài 19h–23h, báo Nhật Anh trước. Kiểm sau deploy:

```bash
docker logs --since 10m sttservice-stt-worker-1 2>&1 | tail -20      # job thường vẫn ghi transcripts/<id>.json
```

---

### Task 11: Tài liệu deploy GCP cho người deploy

**Phân công:** người deploy GCP làm các bước dưới; việc của mình là chép nguyên các bước này vào `docs/deploy-obeval.md` (kèm bảng biến môi trường ở Task 8 Step 8), commit, push và gửi link cho người deploy. Không tự chạy lệnh `gcloud` nào.

**Files:**
- Create: `docs/deploy-obeval.md`

Các bước cần có trong tài liệu (người deploy chạy). Thay `<P_RUN>` = project đặt Cloud Run của obeval, `<P_BUCKET>` = project của bucket (trả lời ở "Đầu vào cần có").

- [ ] **Step 1: Kiểm bucket hỗ trợ IAM condition**

```bash
gcloud storage buckets describe gs://teenup-transcripts --format="value(uniform_bucket_level_access,project_number)"
```
Expected: `True`. Nếu `False`: **dừng**, báo sếp (bật uniform access ảnh hưởng mọi service đang dùng ACL của bucket).

- [ ] **Step 2: Service account và quyền**

```bash
gcloud iam service-accounts create obeval-runner --project <P_RUN> --display-name "obeval Cloud Run"
SA=obeval-runner@<P_RUN>.iam.gserviceaccount.com
gcloud projects add-iam-policy-binding tcservices2027 --member serviceAccount:$SA --role roles/aiplatform.user
gcloud projects add-iam-policy-binding <P_RUN> --member serviceAccount:$SA --role roles/cloudtasks.enqueuer
gcloud storage buckets add-iam-policy-binding gs://teenup-transcripts --member serviceAccount:$SA \
  --role roles/storage.objectViewer \
  --condition='title=onboarding-only,expression=resource.name.startsWith("projects/_/buckets/teenup-transcripts/objects/transcripts/onboarding/")'
```

- [ ] **Step 3: Kiểm quyền chỉ đọc đúng prefix** (impersonate SA, cần quyền Token Creator tạm thời)

```bash
echo '{"check":"iam"}' | gcloud storage cp - gs://teenup-transcripts/transcripts/onboarding/_iam-check.json   # bằng tài khoản của anh
gcloud storage cat gs://teenup-transcripts/transcripts/onboarding/_iam-check.json --impersonate-service-account $SA   # đọc được
gcloud storage ls gs://teenup-transcripts/transcripts/ --impersonate-service-account $SA                                 # PHẢI bị từ chối
gcloud storage rm gs://teenup-transcripts/transcripts/onboarding/_iam-check.json
```

- [ ] **Step 4: Lifecycle 90 ngày — gộp với luật đang có, không ghi đè**

```bash
gcloud storage buckets describe gs://teenup-transcripts --format="json(lifecycle_config)" > lifecycle-current.json
python - <<'PY'
import json
cur = json.load(open("lifecycle-current.json")).get("lifecycle_config") or {}
rules = cur.get("rule", [])
new = {"action": {"type": "Delete"}, "condition": {"age": 90, "matchesPrefix": ["transcripts/onboarding/"]}}
if new not in rules:
    rules.append(new)
json.dump({"rule": rules}, open("lifecycle-new.json", "w"), indent=2)
print(len(rules), "luật")
PY
gcloud storage buckets update gs://teenup-transcripts --lifecycle-file=lifecycle-new.json
gcloud storage buckets describe gs://teenup-transcripts --format="json(lifecycle_config)"
```
Expected: luật cũ vẫn còn, thêm đúng một luật `transcripts/onboarding/` 90 ngày. Lưu `lifecycle-current.json` vào `D:\TeenCare\Plan\` làm bản lưu.

- [ ] **Step 5: Secret Manager**

```bash
python -c "import secrets;print(secrets.token_urlsafe(32))" | gcloud secrets create obeval-api-token --project <P_RUN> --data-file=-
gcloud secrets create obeval-db-dsn --project <P_RUN> --data-file=<file tạm chứa DSN dev, xoá ngay sau>
gcloud secrets create obeval-script --project <P_RUN> --data-file=data/raw/090426_SEC_Script_Onboarding.md
for s in obeval-api-token obeval-db-dsn obeval-script; do
  gcloud secrets add-iam-policy-binding $s --project <P_RUN> --member serviceAccount:$SA --role roles/secretmanager.secretAccessor
done
```

- [ ] **Step 6: Hàng đợi Cloud Tasks**

```bash
gcloud tasks queues create obeval-onboarding --project <P_RUN> --location asia-southeast1 \
  --max-attempts 5 --min-backoff 60s --max-concurrent-dispatches 2
```

- [ ] **Step 7: Cho temp-transcript đọc folder Onboarding** — lấy SA của temp-transcript:

```bash
gcloud run services describe temp-transcript --region asia-east1 --format="value(spec.template.spec.serviceAccountName)"
```
Chia sẻ folder Drive Onboarding (quyền Viewer) cho email đó.

- [ ] **Step 8: Deploy bản dev** (DB dev, `OBEVAL_PUBLISH=false`)

```bash
gcloud run deploy obeval-dev --source . --project <P_RUN> --region asia-southeast1 --service-account $SA \
  --timeout 900 --concurrency 1 --max-instances 5 --memory 1Gi --cpu 1 --allow-unauthenticated \
  --set-secrets "OBEVAL_DB_DSN=obeval-db-dsn:latest,OBEVAL_API_TOKEN=obeval-api-token:latest,/secrets/script/script.md=obeval-script:latest" \
  --set-env-vars "OBEVAL_SCRIPT=/secrets/script/script.md,OBEVAL_PUBLISH=false,OBEVAL_GOOD_THRESHOLD=0.80,OBEVAL_GCP_PROJECT=tcservices2027,OBEVAL_GCP_LOCATION=us-central1,OBEVAL_TEMP_TRANSCRIPT_URL=https://temp-transcript-588651614395.asia-east1.run.app,OBEVAL_TASKS_PROJECT=<P_RUN>,OBEVAL_TASKS_LOCATION=asia-southeast1,OBEVAL_TASKS_QUEUE=obeval-onboarding"
URL=$(gcloud run services describe obeval-dev --project <P_RUN> --region asia-southeast1 --format="value(status.url)")
gcloud run services update obeval-dev --project <P_RUN> --region asia-southeast1 --update-env-vars OBEVAL_SELF_URL=$URL
curl -s $URL/healthz
```
Expected: `{"status":"ok","service":"obeval"}`. Nếu Task 4 chốt `OBEVAL_RUNS=5` thì thêm vào `--set-env-vars`.

---

### Task 12: Apps Script — thêm nhánh onboarding vào script đồng bộ recording đang chạy

Script hiện tại (`syncMeetRecordings`, trigger 15 phút) quét mp4 do tài khoản chạy script sở hữu trong các thư mục "Google Meet", chỉ lấy buổi có **tên thư mục** khớp `MEETING_PATTERN` (1:1 hàng tuần), chuyển sang folder `Record` (`PUBLIC_FOLDER_ID`) rồi gọi `session-on-trigger /drive-webhook`. Buổi onboarding hiện bị bỏ qua và nằm yên trong "Google Meet".

Thêm nhánh onboarding **trong cùng project Apps Script** (cùng tài khoản sở hữu recording, cùng khoá `LockService`), tách riêng mọi thứ của onboarding:

| | 1:1 hàng tuần (giữ nguyên) | Onboarding (mới) |
|---|---|---|
| Nhận diện (tên thư mục buổi) | `MEETING_PATTERN` | `ONBOARDING_PATTERN` = `Gia sư tâm lý 1:1 Onboarding -TC…` |
| Chuyển tới | `Record` (`PUBLIC_FOLDER_ID`) | folder Onboarding **giới hạn quyền** (Script Property `ONBOARDING_FOLDER_ID`) |
| Hàng chờ | `PENDING_RECORDINGS` | `PENDING_ONBOARDING` |
| Gọi | `session-on-trigger /drive-webhook` (mảng file) | `obeval /v1/recordings` (một file, header `X-Obeval-Token`) |
| Cảnh báo | `ALERT_EMAIL` | Script Property `ONB_ALERT_EMAIL` |

Thiếu Script Property nào của onboarding, hoặc folder Onboarding đang để "ai có link cũng xem được", thì nhánh onboarding tự tắt và ghi log — nhánh hàng tuần không bị ảnh hưởng.

**Files:**
- Create: `tools/apps_script/onboarding.gs` (bản lưu trong repo của file mới thêm vào project Apps Script; không chứa ID folder hay token — đọc từ Script Properties)
- Modify (trong project Apps Script, file `Code.gs` hiện có): `scanAndMove`, `syncMeetRecordings`, `backfillOldRecordings`, `getPending`, `setPending`, `addPending`

**Interfaces:**
- Consumes: `POST /v1/recordings` (Task 8) trả `{"status": "queued" | "in_progress" | "already_done" | "unmatched" | "ignored", ...}`, HTTP 200; 401 khi sai token.
- Produces: hàm `isOnboardingMeeting(name)`, `onboardingRoot()`, `sendPendingOnboarding()`, `markRecentPendingOnboarding()` dùng chung global scope với `Code.gs`.

- [ ] **Step 1: Chuẩn bị (người giữ tài khoản chạy script)**
  - Xác nhận recording onboarding có nằm trong thư mục "Google Meet" của **chính tài khoản chạy script** không (`'me' in owners`). Nếu buổi onboarding do tài khoản khác tổ chức (vd lịch của hệ thống đặt lịch), recording nằm ở Drive tài khoản đó: **dừng**, báo sếp — phải chạy script ở tài khoản đó.
  - Tạo folder `Onboarding recordings` cạnh `Record`, chia sẻ **chỉ** cho: SA của temp-transcript (Viewer, email lấy ở Task 11 Step 7) và nhóm PDC. Không bật "ai có link".
  - Script Properties: `ONBOARDING_FOLDER_ID`, `OBEVAL_URL` (URL `obeval-dev` trước, `obeval` prod sau), `OBEVAL_TOKEN` (giá trị secret `obeval-api-token`), `ONB_ALERT_EMAIL`.

- [ ] **Step 2: Viết `tools/apps_script/onboarding.gs`** (thêm vào project Apps Script dưới dạng file mới cùng tên)

```javascript
// ---- Onboarding → obeval (pdc-onboarding-eval) ----
// Tách hẳn khỏi luồng 1:1 hàng tuần: folder riêng giới hạn quyền, hàng chờ riêng, endpoint riêng.
// Script Properties: ONBOARDING_FOLDER_ID, OBEVAL_URL, OBEVAL_TOKEN, ONB_ALERT_EMAIL.
const ONBOARDING_PATTERN = /^TeenCare\s*-\s*Gia sư tâm lý 1[:_]1 Onboarding\s*-\s*TC\d+/i;
const ONB_PENDING_KEY = 'PENDING_ONBOARDING';
const OBEVAL_OK = ['queued', 'in_progress', 'already_done'];

let onbCfgCache_;

// null = nhánh onboarding tắt (thiếu cấu hình hoặc folder đang public) — luồng hàng tuần chạy bình thường
function onboardingConfig_() {
  if (onbCfgCache_ !== undefined) return onbCfgCache_;
  onbCfgCache_ = null;
  const p = PropertiesService.getScriptProperties();
  const cfg = {folderId: p.getProperty('ONBOARDING_FOLDER_ID'), url: p.getProperty('OBEVAL_URL'),
               token: p.getProperty('OBEVAL_TOKEN'), alert: p.getProperty('ONB_ALERT_EMAIL')};
  if (!cfg.folderId || !cfg.url || !cfg.token) {
    console.warn('Onboarding: thiếu Script Properties — bỏ qua nhánh onboarding');
    return null;
  }
  const folder = DriveApp.getFolderById(cfg.folderId);
  if (folder.getSharingAccess() === DriveApp.Access.ANYONE_WITH_LINK) {
    console.error('Onboarding: folder đang để ai có link cũng xem được (video trẻ em) — KHÔNG chuyển file');
    return null;
  }
  cfg.folder = folder;
  onbCfgCache_ = cfg;
  return cfg;
}

function isOnboardingMeeting(name) {
  return onboardingConfig_() !== null && ONBOARDING_PATTERN.test(name.normalize('NFC'));
}

function onboardingRoot() {
  return onboardingConfig_().folder;
}

// Gửi obeval các file trong hàng chờ đã nằm trong folder Onboarding; lỗi thì giữ lại để lượt sau gửi tiếp
function sendPendingOnboarding() {
  const cfg = onboardingConfig_();
  if (!cfg) return;
  const pending = getPending(ONB_PENDING_KEY);
  const noMatch = [];
  const expired = [];
  for (const id of Object.keys(pending)) {
    const isExpired = Date.now() - pending[id] > SEND_MAX_AGE_DAYS * DAY_MS;
    let label = 'https://drive.google.com/file/d/' + id + '/view';
    let reason = 'chưa chuyển được sang folder Onboarding';
    try {
      const video = DriveApp.getFileById(id);
      label = video.getName() + '\n  ' + video.getUrl();
      const meeting = firstParent(video);
      const parent = meeting ? firstParent(meeting) : null;
      if (parent && parent.getId() === cfg.folderId) {
        const result = notifyObeval_(video, cfg);
        if (result.status === 'sent') {
          video.setDescription(MARK_SENT);
          delete pending[id];
          continue;
        }
        if (result.status === 'no-match') {
          video.setDescription(MARK_NO_MATCH);
          noMatch.push(label + '\n  Lý do: ' + result.detail);
          delete pending[id];
          continue;
        }
        reason = result.detail;
      }
    } catch (e) {
      reason = e.message;
      console.error('Onboarding: lỗi gửi file ' + id + ': ' + e.message);
    }
    if (isExpired) {
      expired.push(label + '\n  Lý do: ' + reason);
      delete pending[id];
    }
  }
  setPending(pending, ONB_PENDING_KEY);
  if (cfg.alert && noMatch.length) {
    MailApp.sendEmail(cfg.alert, '[Onboarding recording] ' + noMatch.length + ' file không khớp booking',
      'obeval không ghép được với booking onboarding nào (no_booking: sai mã TC / lệch giờ > 90 phút; ' +
      'unparsable_name: tên file không đọc được). Sửa booking xong chạy markRecentPendingOnboarding.\n\n' +
      noMatch.join('\n\n'));
  }
  if (cfg.alert && expired.length) {
    MailApp.sendEmail(cfg.alert, '[Onboarding recording] ' + expired.length + ' file bị bỏ sau ' + SEND_MAX_AGE_DAYS + ' ngày lỗi',
      'Gửi obeval không thành công trong ' + SEND_MAX_AGE_DAYS + ' ngày.\n\n' + expired.join('\n\n'));
  }
}

// 'sent' = obeval đã nhận (đang xử lý / đã xong) · 'no-match' = không có booking khớp · 'error' = lượt sau gửi lại
function notifyObeval_(video, cfg) {
  const payload = {id: video.getId(), name: video.getName(), webViewLink: video.getUrl(),
                   createdTime: video.getDateCreated().toISOString()};
  try {
    const res = UrlFetchApp.fetch(cfg.url.replace(/\/$/, '') + '/v1/recordings', {
      method: 'post', contentType: 'application/json', muteHttpExceptions: true,
      headers: {'X-Obeval-Token': cfg.token}, payload: JSON.stringify(payload),
    });
    const code = res.getResponseCode();
    const text = res.getContentText();
    console.log('obeval ' + code + ': ' + video.getName() + ' → ' + text);
    if (code !== 200) return {status: 'error', detail: 'HTTP ' + code + ': ' + text.slice(0, 200)};
    const body = JSON.parse(text);
    if (OBEVAL_OK.indexOf(body.status) >= 0) return {status: 'sent'};
    if (body.status === 'unmatched' || body.status === 'ignored') return {status: 'no-match', detail: body.reason || body.status};
    return {status: 'error', detail: 'obeval trả: ' + text.slice(0, 200)};
  } catch (e) {
    console.error('Onboarding: lỗi gọi obeval ' + video.getName() + ': ' + e.message);
    return {status: 'error', detail: e.message};
  }
}

// Chạy tay sau khi sửa booking: đưa mp4 trong folder Onboarding tạo trong 2 ngày mà chưa gửi vào hàng chờ
function markRecentPendingOnboarding() {
  const cfg = onboardingConfig_();
  if (!cfg) return;
  const cutoff = Date.now() - SEND_MAX_AGE_DAYS * DAY_MS;
  const files = searchMp4Since(cutoff);
  while (files.hasNext()) {
    const video = files.next();
    const meeting = firstParent(video);
    const parent = meeting ? firstParent(meeting) : null;
    if (!parent || parent.getId() !== cfg.folderId) continue;
    if (video.getDateCreated().getTime() > cutoff && video.getDescription() !== MARK_SENT) {
      video.setDescription(MARK_PENDING);
      addPending(video.getId(), ONB_PENDING_KEY);
      console.log('Onboarding: đánh dấu pending ' + video.getName());
    }
  }
}
```

- [ ] **Step 3: Sửa `Code.gs` — hàng chờ nhận tên khoá** (mặc định giữ khoá cũ, nên mọi lời gọi cũ không đổi):

```javascript
function getPending(key) {
  return JSON.parse(PropertiesService.getScriptProperties().getProperty(key || PENDING_KEY) || '{}');
}

function setPending(pending, key) {
  PropertiesService.getScriptProperties().setProperty(key || PENDING_KEY, JSON.stringify(pending));
}

function addPending(id, key) {
  const pending = getPending(key);
  if (!(id in pending)) {
    pending[id] = Date.now();
    setPending(pending, key);
  }
}
```

- [ ] **Step 4: Sửa `Code.gs` — `scanAndMove` phân loại buổi.** Thay khối từ `if (!meetingNames.has(meetingId)) {` tới hết `console.log('Đã chuyển: ' ...)` bằng:

```javascript
      if (!meetingNames.has(meetingId)) {
        const root = firstParent(meeting);
        const name = meeting.getName();
        const active = root !== null && activeRoots.has(root.getId());
        const kind = !active ? ''
          : MEETING_PATTERN.test(name.normalize('NFC')) ? 'weekly'
          : isOnboardingMeeting(name) ? 'onboarding' : '';
        meetingNames.set(meetingId, {name: name, kind: kind});
      }
      const m = meetingNames.get(meetingId);
      if (!m.kind) continue;
      const onboarding = m.kind === 'onboarding';

      // Đánh dấu TRƯỚC khi chuyển: bị ngắt giữa chừng thì file vẫn còn trong danh sách gửi
      if (video.getDateCreated().getTime() > sendCutoff) {
        video.setDescription(MARK_PENDING);
        addPending(video.getId(), onboarding ? ONB_PENDING_KEY : PENDING_KEY);
      }
      video.moveTo(getOrCreateFolder(onboarding ? onboardingRoot() : publicRoot, m.name));
      console.log('Đã chuyển' + (onboarding ? ' (onboarding)' : '') + ': ' + m.name + ' / ' + video.getName());
```

- [ ] **Step 5: Sửa `Code.gs` — gọi gửi onboarding** trong `syncMeetRecordings` và `backfillOldRecordings`, ngay sau `sendPending();`:

```javascript
    sendPendingOnboarding();
```

- [ ] **Step 6: Thử trên `obeval-dev`, không để file thật bị gửi sang prod**
  1. Lưu bản sao `Code.gs` hiện tại vào `D:\TeenCare\Plan\apps-script-backup-<ngày>.gs` trước khi sửa.
  2. Tắt trigger `syncMeetRecordings` tạm thời; đặt `OBEVAL_URL` = `obeval-dev`.
  3. Chạy tay `syncMeetRecordings`. Expected trong log: các file hàng tuần vẫn `Đã chuyển: …` sang `Record` và `Worker 200` như cũ; file onboarding `Đã chuyển (onboarding): …` và `obeval 200: … → {"status":"queued"...}` (hoặc `unmatched` nếu booking không có trên DB dev — đúng hành vi).
  4. Chạy lại lần nữa. Expected: không gửi lại file nào (`PENDING_ONBOARDING` rỗng).
  5. Đổi tạm `ONBOARDING_FOLDER_ID` sang một folder để "ai có link" → chạy → log `KHÔNG chuyển file`, file onboarding nằm yên, file hàng tuần vẫn chạy. Trả lại ID đúng.
  6. Bật lại trigger.

- [ ] **Step 7: Commit bản lưu**

```bash
git add tools/apps_script/onboarding.gs
git commit -m "feat(apps-script): nhánh onboarding trong script đồng bộ recording, gọi obeval"
```

### Task 13: Chạy thử đầu-cuối trên dev, rồi lên prod ở chế độ im lặng

- [ ] **Step 1: Theo dõi ca thử ở Task 12** tới khi xong (5 phút/lượt):

```bash
gcloud run services logs read obeval-dev --project <P_RUN> --region asia-southeast1 --limit 50
psql "$OBEVAL_DB_DSN" -c "select status, attempts, overall, published_at, error from public.onboarding_evaluations where booking_id = '<booking giả>'"
```
Expected: `status` đi `processing` → `done` (hoặc `insufficient` nếu STT không ra vai), `published_at` null; trên GCS có `transcripts/onboarding/<booking giả>.json`; **không** có `transcripts/<booking giả>.json`.

- [ ] **Step 2: Thử gửi lại** — gọi `/v1/recordings` lần nữa với đúng file đó.
Expected: `{"status":"already_done"}`; không có lượt chấm thứ hai trong log (không tốn thêm tiền Gemini).

- [ ] **Step 3: Đưa migration vào TeenCareBooking**

```bash
cd d:/TeenCare/TeenCareBooking && git switch tanh/dev/onboarding-ai-report
mkdir -p supabase/migrations
cp ../pdc-onboarding-eval/sql/001_onboarding_evaluations.sql supabase/migrations/20261014000001_onboarding_evaluations.sql
cp ../pdc-onboarding-eval/sql/002_seed_onboarding_criteria.sql supabase/migrations/20261014000002_onboarding_criteria_seed.sql
cp ../pdc-onboarding-eval/sql/003_obeval_writer.sql supabase/migrations/20261014000003_obeval_writer.sql
git add supabase/migrations && git commit -m "feat(db): bảng kết quả AI chấm onboarding, role obeval_writer, RLS"
git push
```
Mở PR; **chủ DB prod** chạy 3 file trên `lhprkkbdeivwmsnwsdhq` rồi đặt mật khẩu `obeval_writer`. Agent không chạy lệnh nào lên prod.

- [ ] **Step 4: Người deploy GCP deploy prod** — tạo secret `obeval-db-dsn-prod` (DSN prod của `obeval_writer`), deploy service `obeval` bằng đúng lệnh Task 11 Step 8 với tên `obeval` và secret prod, **`OBEVAL_PUBLISH=false`**. Apps Script thật: Script Properties trỏ folder thật + `obeval` prod, chạy `installTrigger`.

- [ ] **Step 5: Theo dõi 1 tuần chạy im lặng** — mỗi ngày:

```sql
select status, count(*) from public.onboarding_evaluations where created_at > now() - interval '1 day' group by 1;
select reason, count(*) from public.onboarding_recording_unmatched where last_seen_at > now() - interval '1 day' group by 1;
select booking_id, attempts, error from public.onboarding_evaluations where status = 'processing' and updated_at < now() - interval '3 hours';
```
Expected: số ca `done` ≈ số buổi onboarding đã diễn ra; ca kẹt và ca không khớp được xử lý tay.

- [ ] **Step 6: Bật hiển thị cho Mentor — chỉ khi Task 4 kết luận "đạt"** và PDC đã chốt ngưỡng:

```bash
gcloud run services update obeval --project <P_RUN> --region asia-southeast1 \
  --update-env-vars OBEVAL_PUBLISH=true,OBEVAL_GOOD_THRESHOLD=<ngưỡng PDC chốt>
set OBEVAL_DB_DSN=<DSN prod obeval_writer>
python run.py publish
```
Expected: in số ca vừa cho Mentor xem; Mentor test thấy nút "Góp ý AI" ở trang Lịch đã đặt.

---

## Ngoài phạm vi plan này

- Sửa gốc luật gán vai Phụ huynh ↔ Học sinh trong STT: obeval đã tự đổi chỗ khi thấy lời kiểu trẻ con (`transcript._child_label_swapped`).
- Email cho Mentor, thông báo khi có báo cáo mới, giao diện dashboard (Data Analyst dựng từ DB).
- Gỡ session-on-trigger / session-data-worker: không đụng tới.
