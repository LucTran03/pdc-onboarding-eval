# Dữ liệu AI chấm buổi onboarding — hướng dẫn cho dashboard

> Cập nhật: 13/10/2026 · Người viết: Tuấn Anh · Người đọc: Data Analyst build dashboard PDC · Trạng thái: chạy trên DB **dev**, có 2 ca thử nghiệm

## 1. Data nằm ở đâu

| Môi trường | Supabase project | Ghi chú |
|---|---|---|
| **Dev (hiện tại)** | `ktazdnmmpudgvewkbgaq` | 5 bảng đã tạo, có 2 ca thử nghiệm (booking giả) |
| Prod (sau này) | `lhprkkbdeivwmsnwsdhq` (DB đặt lịch MentorBookingSEC) | Chưa tạo bảng; cần PR vào repo TeenCareBooking, chủ DB duyệt |

- Bảng nằm **cùng DB với `bookings`** (DB đặt lịch, repo TeenCareBooking), vì buổi onboarding chỉ tồn tại ở `bookings`, không có trong `sessions` của CRMxLMS hay TeenCareParent.
- Khoá chung: **`booking_id` = `bookings.id`** (cũng = `mentor_session_bookings.external_booking_id` bên TeenCareParent và `pdc_mentorsec_bookings_cache.id` bên CRMxLMS, nếu cần nối sang hệ thống khác).
- Đọc bằng **service role key** (server). Key xin Tuấn Anh, không để trong code phía trình duyệt.
- DDL: `sql/001_onboarding_evaluations.sql`; danh mục tiêu chí: `sql/002_seed_onboarding_criteria.sql` (repo pdc-onboarding-eval).

## 2. Luồng dữ liệu

```
Recording buổi onboarding → STT (chia người nói) → transcript trên GCS
  → AI chấm (Gemini, 3 lần lấy đa số) → tính điểm bằng code
  → ghi DB: 1 dòng onboarding_evaluations + 37 dòng onboarding_evaluation_steps (+ audit)
```

Mỗi buổi **một dòng**; chấm lại thì **ghi đè** (37 dòng steps được xoá và ghi lại). Hiện ghi bằng lệnh tay (`python run.py push-db`); giai đoạn sau sẽ tự động sau mỗi ca.

## 3. Các bảng

### 3.1 `onboarding_evaluations` — mỗi buổi một dòng (bảng chính cho dashboard)

| Cột | Kiểu | Ý nghĩa |
|---|---|---|
| `booking_id` | uuid, PK, FK → `bookings.id` | Mã buổi; dùng làm link "xem chi tiết" |
| `status` | text | `processing` · `done` · `error` · `insufficient` (thiếu dữ liệu, **không tính là 0%**) |
| `session_date` | date | Ngày buổi học (giờ VN) |
| `duration_sec` | integer | Thời lượng bản ghi |
| `overall` | numeric 0–1 | **% follow kịch bản toàn ca** (vd 0.7284 = 72,8%) |
| `threshold` | numeric | Ngưỡng lúc chấm (hiện 0.80). Dashboard nên so `overall` với ngưỡng **hiện hành**, không dùng cột này để quyết đạt/không đạt |
| `activities` | jsonb | Điểm 5 hoạt động — xem 4.1 |
| `mentor_report` | jsonb | Nội dung báo cáo ngắn Mentor nhận — xem 4.2 |
| `flags` | jsonb | Cờ hành vi — xem 4.3 |
| `criteria_version` | text | Phiên bản bộ tiêu chí (hiện `2026-10-09`); không trộn version khi so xu hướng |
| `model` | text | Model AI đã chấm |
| `scored_at` | timestamptz | Thời điểm chấm |
| `published_at` | timestamptz | Thời điểm cho Mentor xem (null = chưa) |
| `email_to`, `email_sent_at` | text, timestamptz | Gửi email Mentor (chưa dùng) |
| `error` | text | Lỗi xử lý (khi `status = error`) |
| `recording_file_id` | text | Mã file recording trên Google Drive (cột điều phối của obeval, dashboard không cần) |
| `recording_url` | text | Link Drive gửi cho dịch vụ chuyển giọng nói (điều phối, dashboard không cần) |
| `run_id` | bigint | Mỗi lần bắt đầu chấm lại có `run_id` mới; tác vụ cũ bị bỏ (điều phối) |
| `attempts` | integer | Số lần thử xử lý, mặc định 0 (điều phối) |
| `created_at`, `updated_at` | timestamptz | |

### 3.2 `onboarding_evaluation_steps` — 37 dòng mỗi buổi (cho chart "phần hay sai")

| Cột | Kiểu | Ý nghĩa |
|---|---|---|
| `booking_id` | uuid, FK → `onboarding_evaluations` | |
| `criterion_id` | text | `OB01`…`OB37` |
| `activity` | smallint | Hoạt động 1–5 của tiêu chí |
| `status` | text | `FF` làm đủ · `PF` làm một phần · `NF` chưa làm · `NA` không áp dụng · `NE` không đủ dữ liệu |

"Sai kịch bản" = `status in ('NF','PF')`. Khoá chính (`booking_id`, `criterion_id`).

### 3.3 `onboarding_criteria` — danh mục tiêu chí (tên tiếng Việt, "cần làm gì")

| Cột | Kiểu | Ý nghĩa |
|---|---|---|
| `criterion_id` | text | `OB01`…`OB37` |
| `version` | text | Khớp `onboarding_evaluations.criteria_version` |
| `name` | text | Tên bước, vd "Khai thác kết quả WCA và nhu cầu xây dựng thói quen" |
| `activity` | smallint | 1–5 |
| `requirements` | jsonb (mảng chuỗi) | Những việc Mentor cần làm — dùng cho "Đề xuất cải thiện" |

Tên 5 hoạt động (không có bảng riêng): 1 Chào hỏi, giới thiệu và thiết lập cam kết · 2 Khởi động và giao nhiệm vụ · 3 Học riêng cùng con · 4 Học cùng gia đình · 5 Trao đổi riêng với phụ huynh. Trọng số 10 / 10 / 35 / 20 / 25%.

### 3.4 `onboarding_evaluation_audit` — bản đầy đủ để kiểm định (**không dùng cho dashboard chung**)

`booking_id`, `result` (jsonb đầy đủ 37 tiêu chí kèm trích dẫn lời gia đình), `stability`, `ai_issues`, `quote_stats`, `transcript_warnings`, `transcript_uri`, `model_raw_uri`, `cost_usd`, `usage`. Có **dữ liệu cá nhân của trẻ vị thành niên** — chỉ dùng cho trang chi tiết có phân quyền. Hiện chưa đẩy dữ liệu vào bảng này.

### 3.5 `onboarding_evaluation_feedback` — Mentor phản hồi "góp ý chưa đúng" (chưa có dữ liệu)

`id`, `booking_id`, `mentor_id`, `item_key` (vd `improvement:OB31`), `verdict` (`agree` / `disagree`), `comment`, `created_at`. Dùng sau này để đo tỷ lệ góp ý phù hợp.

### 3.6 Bảng có sẵn để nối (DB đặt lịch)

| Bảng | Cột hay dùng |
|---|---|
| `bookings` | `id`, `mentor_id`, `event_type_id`, `start_at`, `status`, `region`, `student_code` |
| `event_types` | `id`, `name` — loại buổi; hiện chỉ chấm **"Gia sư tâm lý 1:1 Onboarding"** |
| `mentors` | `id`, `full_name`, `email` — **không hiển thị trên dashboard chung** (yêu cầu PDC v3.0: không tên Mentor, không xếp hạng) |

### 3.7 `onboarding_recording_unmatched` — recording chưa ghép được booking (**không dùng cho dashboard**)

| Cột | Kiểu | Ý nghĩa |
|---|---|---|
| `file_id` | text, PK | Mã file recording trên Drive |
| `file_name` | text | Tên file (**có tên / SĐT phụ huynh**) |
| `reason` | text | `unparsable_name` (không đọc được tên file) · `no_booking` (không tìm thấy booking khớp) · `duplicate_recording` (booking đã có recording được chấm; file này không bị chấm đè, chờ người xem xét) |
| `first_seen_at`, `last_seen_at` | timestamptz | Lần đầu / lần gần nhất obeval thấy file này |

Chỉ admin đọc được; dùng để xử lý tay, không đưa lên dashboard chung. DDL: `sql/003_obeval_writer.sql`.

## 4. Cấu trúc các cột JSON

### 4.1 `activities`

```json
[{"activity": 3, "score": 0.69, "counts": {"FF": 7, "PF": 4, "NF": 2},
  "start": 784.0, "end": 1700.0, "estimated": false}]
```
`score` 0–1 (null nếu không chấm được); `start` / `end` là giây tính từ đầu bản ghi; `estimated = true` khi mốc giờ do code ước lượng.

### 4.2 `mentor_report` (báo cáo ngắn Mentor thấy)

```json
{"version": 1, "overall": 0.7284, "threshold": 0.8, "classification": "Chệch kịch bản", "summary": "...",
 "activities": [{"activity": 1, "name": "...", "score": 0.7, "time": "00:01:14–00:07:14 · 6 phút (chuẩn 5 phút)"}],
 "not_followed": [{"criterion_id": "OB31", "step": "...", "activity": 5, "status": "NF", "status_label": "Chưa làm",
                   "reason": "...", "missing": ["..."], "timestamp": "00:51:45"}],
 "improvements": [{"criterion_id": "OB31", "step": "...", "timestamp": "...", "problem": "...",
                   "suggestion": "...", "suggested_script": "..."}]}
```
Chữ trong `reason` / `suggestion` do AI viết, **có thể nhắc tên phụ huynh / học sinh** → không đưa lên dashboard chung. Dashboard dùng mã (`criterion_id`) + tên từ `onboarding_criteria`.

### 4.3 `flags`

```json
[{"id": "F09", "script_instructed": true}]
```
10 cờ hành vi `F01`…`F10` (theo brief PDC), vd F01 độc thoại nhiều, F09 gây áp lực / suy diễn đồng ý, F10 không chốt bước tiếp theo. `script_instructed = true`: hành vi có trong kịch bản, PDC đang xem lại cách đánh giá.

## 5. Ba phần dashboard và câu truy vấn

Điều kiện chung cho mọi phần: `status = 'done'` + lọc theo khoảng ngày `session_date`. Ngưỡng tiêu chuẩn: **80%**.

**a) Tổng số ca, % follow kịch bản, % ca follow, % ca không follow**
```sql
select count(*)                     as tong_so_ca,
       avg(overall)                 as ty_le_follow_tb,
       avg((overall >= 0.80)::int)  as ty_le_ca_follow,
       avg((overall <  0.80)::int)  as ty_le_ca_khong_follow
from onboarding_evaluations
where status = 'done' and session_date between :tu and :den;
```
Ca `status = 'insufficient'` đếm riêng (thẻ "Ca thiếu dữ liệu"), không đưa vào trung bình.

**b) Danh sách ca dưới chuẩn (< 80%) + link**
```sql
select e.booking_id, e.session_date, e.overall, e.activities
from onboarding_evaluations e
where e.status = 'done' and e.overall < 0.80
  and e.session_date between :tu and :den
order by e.overall;
```
Link mỗi dòng → trang chi tiết theo `booking_id` (trang có phân quyền, đọc bảng audit). "Hoạt động thấp nhất" lấy phần tử có `score` nhỏ nhất trong `activities`.

**c) Chart các phần hay bị sai kịch bản nhất**
```sql
select c.name, c.activity, count(*) as so_ca
from onboarding_evaluation_steps s
join onboarding_evaluations e using (booking_id)
join onboarding_criteria c on c.criterion_id = s.criterion_id and c.version = e.criteria_version
where s.status in ('NF', 'PF')
  and e.status = 'done' and e.session_date between :tu and :den
group by c.name, c.activity
order by so_ca desc
limit 10;
```

## 6. Lưu ý

- **Dữ liệu hiện có chỉ là thử nghiệm**: 2 ca trên dev, điểm 70,2% và 72,8%, gắn với 2 booking giả. Dữ liệu thử nghiệm / nghiệm thu chỉ nằm ở dev; prod chỉ nhận ca vận hành thật nên không cần cờ phân biệt.
- Điểm AI **chưa được nghiệm thu** với người chấm tay; chấm lại cùng một ca hiện còn dao động (đã thấy lệch tới 11 điểm %). Không dùng để đánh giá cá nhân Mentor.
- Không hiển thị tên Mentor, không xếp hạng trên dashboard chung (yêu cầu PDC v3.0).
- Bảng audit và chữ tự do trong `mentor_report` có thể chứa dữ liệu cá nhân của trẻ vị thành niên — không xuất ra file / Sheet ngoài hệ thống.
- Đổi ngưỡng (80%) chỉ cần sửa trong truy vấn, không cần chấm lại. Ngưỡng do PDC chốt, hiện tạm 0.80.
- obeval tự động ghi DB bằng role riêng `obeval_writer` (không dùng service-role key): chỉ đọc 6 cột của `bookings` (không có tên / SĐT / email phụ huynh) và chỉ thấy buổi loại "Gia sư tâm lý 1:1 Onboarding"; DDL ở `sql/003_obeval_writer.sql`.
