# Bàn giao — AI chấm buổi onboarding (PDC)

> Cập nhật: 2026-10-12 · Người giao: anh Lực (AI Tech Lead) · Người nhận: Tuấn Anh · Trạng thái: prototype chạy được end-to-end trên dữ liệu giả, chưa chạy trên buổi thật

## 1. Bài toán

- **Nguồn:** task Base 6426152 "Làm công cụ tự động phân tích năng lực chạy kịch bản của SEC".
  - Giao việc: chị Đặng Hương Giang (Giám đốc Học thuật) → Lê Quốc Phong (PDC).
  - Đầu mối PDC: Phong.
- **Yêu cầu:** [`docs/yeu-cau-pdc.md`](docs/yeu-cau-pdc.md).
- **Tài liệu gốc** (brief, đầu ra v3.0, kịch bản) là tài liệu nội bộ, **không có trong repo**. Xin anh Lực.

## 2. Đã có (09/10/2026)

- **Luồng end-to-end:** transcript → Gemini 2.5 Pro (3 lần, lấy đa số) → kiểm trích dẫn → tính điểm → email Mentor + bảng điều khiển + đối chiếu người chấm.
- **Kết quả trên buổi giả `samples/synthetic-01`** (48 phút, có cài lỗi): đạt cả **5/5 chỉ tiêu nghiệm thu**.

  | Chỉ tiêu | Kết quả | Mục tiêu |
  |---|---|---|
  | Trùng phân loại tiêu chí | 86% | ≥ 85% |
  | Lệch tỷ lệ toàn ca | 1,4 điểm % | ≤ 5 |
  | Tìm đúng lỗi | 90% | ≥ 85% |
  | Logic liên kết | 83% | ≥ 80% |
  | NF có dẫn chứng | 100% | 100% |

  Đáp án do chính người viết buổi giả tự đặt, nên **chưa phải số thật**.
- **Review độc lập 3 vòng** ([`docs/reviews/`](docs/reviews/)): mọi lỗi Important đã sửa, mỗi lỗi có test hồi quy. Cổng kiểm thử: 60 test.

## 3. Quyết định thiết kế (đừng đổi khi chưa đo lại)

| Quyết định | Lý do / số đo |
|---|---|
| Gemini 2.5 Pro, không dùng Flash | Flash trượt 3/5 chỉ tiêu (trùng 78%, tìm lỗi 70%, liên kết 33%) |
| Chấm 3 lần, **temperature 1.0 + seed khác nhau**, lấy đa số | 1 lần chạy dao động 76–89% trên cùng một buổi. 3 lần song song ở temperature 0 cho kết quả **giống hệt nhau**, nên không độc lập |
| Model không tự tính điểm; code tính | Tránh cộng sai; đổi ngưỡng thì `rescore` mà không gọi lại model |
| Trích dẫn phải có trong transcript (`verify.py`) | Chống bịa dẫn chứng. Không khớp thì hạ tiêu chí về NE, không vào email |
| Khớp gần đúng không được lệch chữ phủ định / chữ số, kiểm trên chữ **còn dấu** | Bỏ dấu thì "khối" thành "khỏi", tạo phủ định giả (review vòng 3) |
| `minItems/maxItems` bị bỏ khỏi schema gửi Vertex | Vertex báo "too many states". `validate.py` tự kiểm đủ 37/6/≤ 3 |
| Bảng điều khiển chỉ nhận mã có trong danh mục, mã ca được băm | Brief cấm tên Mentor; tên file có thể chứa tên học sinh |
| Che SĐT / số tài khoản **trước** khi gửi model | Dữ liệu gia đình |

## 4. Việc tiếp theo

**Giai đoạn 1 — nghiệm thu với PDC:**
1. ~~Nối **STT có tách người nói** (service của em) vào. Kiểm adapter trong `transcript.py` đọc đúng file JSON đầu ra, và thêm test bằng một file mẫu đã xoá dữ liệu thật.~~ **Xong 12/10:**
   - `transcript.py` đọc JSON STT `PIPELINE=diarized`: đổi vai sang Mentor / Học sinh / Phụ huynh / [VIDEO], tự điền nhãn Mentor, cảnh báo khi `session_flag=insufficient` hoặc `legacy-fallback`.
   - Test bằng mẫu ẩn danh `tests/fixtures/stt_diarized_sample.json`.
   - `tools/stt_local.py` chạy STT ngay trên máy cho 5 video nghiệm thu, vì pipeline mới chưa bật trên server.
   - Đã chạy thật trên 1 file mp4 test (1 phút) và dry-run `obeval`. **Chưa chạy trên buổi onboarding thật.**
2. Xin PDC **5 video kèm phiếu chấm tay** (`python run.py human-template`). Chạy `batch`, rồi `compare --pairs` để có bảng đối chiếu.
3. Chỉnh prompt hoặc danh mục theo các chỗ lệch. Mỗi lần chỉnh, chạy lại cả 5 ca để so.
4. Chờ PDC chốt:
   - cách chấm phần bán hàng khi kịch bản dạy "ưu đãi 24h" mà brief bắt gắn cờ F09 (`script_instructed` đã tách riêng);
   - ngưỡng "thiếu dữ liệu" (NE > 30%; mẫu số có tính NA hay không). Ngưỡng "tuân thủ tốt" đã chốt 80% theo yêu cầu nhận 12/10.

**Giai đoạn 2 — vận hành** (xem [`docs/kha-thi-2026-10-09.md`](docs/kha-thi-2026-10-09.md) §1–2):
5. **Tự nhận ca onboarding:** Apps Script recording (Nhật Anh giữ) hiện chỉ lọc `Gia sư Mentor 1:1 hàng tuần`. Cần thêm nhánh cho tên chứa `Gia sư Mentor 1:1 (Onboard)` hoặc `1:1 Mentor Onboarding`.
6. **Chạy trên Cloud Run:** Apps Script giới hạn 6 phút/lần, một ca mất khoảng 3 phút → cần endpoint riêng.
7. **Gửi email thật:** lấy email Mentor từ bảng `bookings` (DB Booking), thống nhất người nhận và quyền xem với PDC.
8. **Đưa bảng điều khiển lên Command Center:** `dashboard_row.json` đã đúng dạng để ghi lên Sheet hoặc DB.

## 5. Giới hạn đã biết

- **Che số:**
  - không che được số đọc bằng chữ ("không chín một hai…");
  - giá viết liền không đơn vị và ngày tháng bị che dư (chấp nhận được).
- **Transcript không nhãn người nói:** không chặn được trích dẫn ghép lời 2 người. Nên dùng STT có tách người nói.
- **STT gán nhầm người nói:** chỉ chịu được khi phần nhầm ≤ 3 từ và ≤ 25% đoạn trích.
- **STT v1 đảo nhãn Phụ huynh ↔ Học sinh ở buổi onboarding** (12/10, cả 2 ca thật).
  - Nguyên nhân: luật gán vai viết cho buổi 1:1 hàng tuần, coi người đổi lượt với Mentor nhiều nhất là học sinh. Buổi onboarding thì phụ huynh nói riêng với Mentor lâu nhất.
  - `transcript.py` tự đổi lại nhãn khi nhãn "Phụ huynh" có nhiều lời kiểu trẻ con hơn hẳn (`CHILD_CUES`), và ghi cảnh báo.
  - Sửa gốc phải làm ở repo STT (`app/pipeline/roles.py`): cho STT biết loại buổi, chọn ai là con theo cách xưng hô.
  - Câu bị gộp lẫn khi bố/mẹ và con ngồi chung một máy thì đổi nhãn không sửa được.
- **Độ dao động giữa các lần chấm trên buổi thật lớn:** ca TC16542 chấm 3 lượt ra 65,0% / 61,8% / 72,8%; 3 lần chấm trong một lượt chỉ thống nhất 65–70% số tiêu chí. Cần giảm trước khi nghiệm thu (ngưỡng ±5 điểm %).
- **Bảng `transcripts` ở DB TeenCareParent:** không có buổi onboarding nào; chỉ ~3% đoạn có mốc giờ, gần như không có nhãn người nói (đo 09/10).

## 6. An toàn dữ liệu

- **Không commit transcript thật, email, kết quả chấm.** `data/` đã có trong `.gitignore`.
- Chỉ gọi model qua **Vertex của công ty**.
- Trang chi tiết và email có trích lời gia đình → chỉ người có quyền được xem.
- Thư mục recording onboarding trên Drive có video trẻ em: không tải về máy cá nhân khi không cần.
