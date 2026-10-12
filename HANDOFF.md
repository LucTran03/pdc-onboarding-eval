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
1. Nối **STT có tách người nói** (service của em) vào. Kiểm adapter trong `transcript.py` đọc đúng file JSON đầu ra, và thêm test bằng một file mẫu đã xoá dữ liệu thật.
2. Xin PDC **5 video kèm phiếu chấm tay** (`python run.py human-template`). Chạy `batch`, rồi `compare --pairs` để có bảng đối chiếu.
3. Chỉnh prompt hoặc danh mục theo các chỗ lệch. Mỗi lần chỉnh, chạy lại cả 5 ca để so.
4. Chờ PDC chốt:
   - cách chấm phần bán hàng khi kịch bản dạy "ưu đãi 24h" mà brief bắt gắn cờ F09 (`script_instructed` đã tách riêng);
   - ngưỡng "tuân thủ tốt" (đang để 85%) và ngưỡng "thiếu dữ liệu" (NE > 30%; mẫu số có tính NA hay không).

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
- **Bảng `transcripts` ở DB TeenCareParent:** không có buổi onboarding nào; chỉ ~3% đoạn có mốc giờ, gần như không có nhãn người nói (đo 09/10).

## 6. An toàn dữ liệu

- **Không commit transcript thật, email, kết quả chấm.** `data/` đã có trong `.gitignore`.
- Chỉ gọi model qua **Vertex của công ty**.
- Trang chi tiết và email có trích lời gia đình → chỉ người có quyền được xem.
- Thư mục recording onboarding trên Drive có video trẻ em: không tải về máy cá nhân khi không cần.
