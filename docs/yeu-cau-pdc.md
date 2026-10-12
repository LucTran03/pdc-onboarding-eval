# Tool AI đánh giá buổi onboarding (PDC) — chỉ mục và yêu cầu

> Cập nhật: 2026-10-09 · Trạng thái: active · Nguồn: task Base PDC "Làm công cụ tự động phân tích năng lực chạy kịch bản của SEC" (task 6426152; giao: Đặng Hương Giang → Lê Quốc Phong; comment của Phong 08/10 18:14 nhờ anh Lực làm prototype); 3 tài liệu Google đọc qua Chrome 09/10. Đề xuất cũ của em (07/10, trước khi có tài liệu): `de-xuat-bao-cao-buoi-onboarding-2026-10-07.md` (ở workspace anh Lực, không chép sang).

**Hạn:** bản prototype đầu tiên trước **15:00 thứ Sáu 09/10/2026** (Phong đặt).

**Tool prototype:** [`tool/README.md`](../README.md) (`obeval`: transcript → Gemini 2.5 Pro → email Mentor + bảng điều khiển + đối chiếu người chấm) · prompt: [`prompt/README.md`](../prompt/README.md) · khả thi + đo DB: [`kha-thi-2026-10-09.md`](kha-thi-2026-10-09.md).

## 1. Tài liệu nguồn

Bản gốc lưu **ngoài git** tại `data/raw/` (ngoài git; trên máy anh Lực là `D:\teencare-data\pdc-onboarding\raw\`) (tài liệu nội bộ công ty; kịch bản có thông tin tài khoản ngân hàng và chiến thuật bán hàng):

| Tài liệu | File local | Nội dung |
|---|---|---|
| Brief "Onboarding Evaluation_AI Brief" | `Onboarding Evaluation_AI Brief.md` | Bộ tiêu chí chấm (chi tiết ở §2) |
| Kịch bản "090426 - SEC Script Onboarding" | `090426_SEC_Script_Onboarding.txt` | Logic kịch bản + full script 5 hoạt động (bản text, thiếu ~1.200 ký tự cuối do Chrome cắt) |
| Đầu ra "TeenCare_Outcomes AI Agent.docx" (v3.0, 08/10) | `.docx` + `TeenCare_Outcomes_AI_Agent.txt` | Yêu cầu sản phẩm + tiêu chí nghiệm thu (§3) |
| Meeting mẫu (Drive, mp4 1,4 GB, buổi "Gia sư Mentor 1:1 (Onboard)" 28/10/2025) | **chưa tải** (anh bảo bỏ qua) | Recording thật của 1 gia đình |
| File đính kèm comment `TeenCare_De_Bai_Dau_Ra_Danh_Gia_Onboarding_V4.docx` | **chưa tải được** | Có thể là bản mới hơn của file Đầu ra |

## 2. Brief — bộ tiêu chí chấm

- **Đối tượng:** Mentor dẫn buổi onboarding với phụ huynh và học sinh. Chấm **theo logic và mục tiêu**, không theo câu chữ.
- **5 hoạt động, có trọng số:**

| Hoạt động | Thời lượng | Trọng số | Tiêu chí |
|---|---|---|---|
| 1. Chào hỏi, giới thiệu, cam kết | 5 phút | 10% | OB01–OB05 |
| 2. Khởi động, giao nhiệm vụ | 2 phút | 10% | OB06–OB07 |
| 3. Học riêng cùng con | 20 phút | 35% | OB08–OB20 |
| 4. Học cùng gia đình (Chim sẻ gọi Đại bàng) | 10 phút | 20% | OB21–OB27 |
| 5. Trao đổi riêng với phụ huynh | 20–25 phút | 25% | OB28–OB37 |

- **6 logic liên kết** LK01–LK06, chấm riêng: Đạt / Đạt một phần / Chưa đạt / Không đủ dữ liệu.
- **5 trạng thái mỗi tiêu chí:** Fully (100%) · Partially (50%) · Not Followed (0%) · N/A · Insufficient Evidence. Mọi nhận định phải có bằng chứng (timestamp + lời thoại).
- **10 cờ hành vi** cần gắn (độc thoại, tự trả lời thay, gây áp lực, suy diễn đồng ý, tiết lộ riêng tư của con…).
- **Gợi ý cải thiện:** tối đa 3 điểm, mỗi điểm 7 phần (tiêu chí · bằng chứng · vấn đề · logic bị ảnh hưởng · gợi ý · câu thoại gợi ý · ưu tiên); tối thiểu 2 điểm làm tốt.

## 3. Đầu ra và nghiệm thu (v3.0)

- **Giai đoạn 1 — kiểm chứng trên 5 video**, so với bộ phận học thuật chấm độc lập:
  - phân loại từng tiêu chí trùng ≥ 85%;
  - tỷ lệ tuân thủ toàn ca lệch ≤ ±5 điểm %;
  - tìm đúng ≥ 85% lỗi;
  - nhận đúng ≥ 80% chỗ chệch logic;
  - ≥ 80% góp ý được đánh giá phù hợp;
  - 100% lỗi quan trọng có dẫn chứng.
- **Giai đoạn 2 — vận hành:**
  - tự nhận mọi ca onboarding;
  - phân biệt người nói;
  - ≥ 95% video hợp lệ có đánh giá, trong 24 giờ;
  - ca thiếu dữ liệu ghi riêng, không tính 0%.
- **Chỉ 2 đầu ra:**
  - (A) **email báo cáo riêng cho Mentor** sau từng ca, tiếng Việt rõ ràng, không chỉ ghi mã OB;
  - (B) **bảng điều khiển Command Center** cho Giám đốc Học thuật và Trợ lý Học thuật: chỉ số tổng hợp, **không xếp hạng, không tên Mentor**.

## 4. Điểm em thấy cần chốt với PDC

1. **Kịch bản và brief mâu thuẫn ở phần bán hàng.**
   - Kịch bản dạy tạo khẩn cấp ("mã ưu đãi chỉ trong 24h", "cần quyết định ngay"), hình phạt nặng và "đợi PH thực sự nói vâng".
   - Brief yêu cầu **gắn cờ "gây áp lực / suy diễn đồng ý"** và không chấm cao hành vi gây áp lực.
   - Mentor làm đúng kịch bản có thể bị gắn cờ → cần PDC quyết cách chấm OB33–OB36.
2. **Nguồn transcript cho prototype:** anh bỏ qua video → cần một transcript buổi onboarding (bản Meet/Gemini, hoặc STT có tách người nói của Tuấn Anh).
3. Tên file buổi đầu có dạng **"Gia sư Mentor 1:1 (Onboard)"**. Apps Script recording hiện chỉ nhận "Gia sư Mentor 1:1 hàng tuần" nên đang bỏ qua các ca này (giai đoạn 2).
4. **Bộ 5 video đã chấm tay** của học thuật là điều kiện để nghiệm thu giai đoạn 1.
