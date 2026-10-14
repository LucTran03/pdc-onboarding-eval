# AI chấm buổi onboarding: cơ chế hoạt động và các điểm cần PDC góp ý

> Cập nhật: 12/10/2026 · Người viết: Tuấn Anh · Người đọc: bộ phận Học thuật (PDC) · Trạng thái: prototype, đã chạy thử trên 2 buổi thật, chưa đối chiếu với người chấm

## 1. Tóm tắt

- **Đầu vào và đầu ra:** hệ thống nhận recording một buổi onboarding và ra 2 kết quả:
  - email góp ý riêng cho Mentor;
  - một dòng số liệu trên bảng điều khiển chung (không tên Mentor, không xếp hạng).
- **Căn cứ chấm:** đúng bộ tiêu chí trong brief của PDC, gồm 37 tiêu chí (OB01–OB37), 6 logic liên kết (LK01–LK06) và 10 cờ hành vi. Kịch bản SEC chỉ dùng để tham chiếu.
- **Tình trạng hiện tại:** đã chạy trên 2 buổi thật ngày 11/10. Kết quả đọc được và có dẫn chứng.
- **Hai điểm chưa ổn:**
  - chấm lại cùng một buổi cho điểm chênh nhau tới 11 điểm %;
  - một số chỗ trong bộ tiêu chí cần PDC làm rõ (mục 7).

## 2. Luồng xử lý một buổi

```
Recording (video)
  │ 1. Chuyển lời nói thành chữ, tách từng người nói, gán vai Mentor / Học sinh / Phụ huynh
  ▼
Bản ghi lời thoại có mốc giờ        ví dụ: [00:13:04] Mentor: Hôm nay con đang cảm thấy thế nào?
  │ 2. Che số điện thoại, số tài khoản
  ▼
AI (Gemini 2.5 Pro) đọc toàn bộ buổi + bộ tiêu chí + kịch bản
  │ 3. Chấm 3 lần độc lập, lấy đa số
  ▼
  │ 4. Kiểm tra: mọi câu AI trích dẫn phải có thật trong bản ghi
  ▼
  │ 5. Tính điểm bằng công thức cố định (AI không tự cộng điểm)
  ▼
Email góp ý cho Mentor  +  Trang chi tiết để kiểm định  +  Bảng điều khiển chung
```

Mỗi buổi khoảng 60 phút xử lý mất khoảng 10 phút. Chi phí khoảng 0,5–0,8 USD.

## 3. AI chấm dựa vào gì

AI được giao đúng các nguyên tắc trong brief:

- **Chấm theo mục tiêu, không theo câu chữ.** Mentor không cần đọc thuộc kịch bản. Ví dụ, hỏi "con chọn 2–3 cảm xúc phù hợp nhất nhé" vẫn tính là làm đủ phần check-in cảm xúc. Nhưng chỉ hỏi "con khỏe không?" thì không đủ.
- **Năm mức cho mỗi tiêu chí:**

  | Mức | Ý nghĩa | Điểm |
  |---|---|---|
  | Làm đủ (FF) | Làm đủ hành vi và nội dung cốt lõi | 100% |
  | Làm một phần (PF) | Có làm nhưng thiếu thành phần quan trọng | 50% |
  | Chưa làm (NF) | Không làm dù có cơ hội và đủ dữ liệu để biết | 0% |
  | Không áp dụng (NA) | Tình huống không phát sinh, ví dụ phụ huynh không hỏi về giá | Không tính |
  | Thiếu dữ liệu (NE) | Bản ghi không đủ để kết luận | Không tính |

- **Mọi nhận định phải có dẫn chứng:** mốc giờ kèm câu nói nguyên văn.
- **Phần tiêu chí có điều kiện được chấm đúng điều kiện:** brief cho phép không đánh trượt Mentor khi con chưa muốn kể nỗi sợ (OB11), hoặc khi không có ôm hay khóc (OB25).
- **Phân biệt kỹ năng sư phạm với kỹ thuật bán hàng.** AI không chấm cao hơn cho hành vi gây áp lực, ép cam kết hay tạo cảm giác tội lỗi.
- **Chấm cả thứ tự các bước.** Ví dụ, phải hiểu nhu cầu gia đình (OB29) trước khi giới thiệu gói và giá, và con phải rời buổi trước phần trao đổi riêng với phụ huynh.

## 4. Cách tính điểm

1. **Điểm từng hoạt động** = trung bình điểm các tiêu chí của hoạt động đó. Tiêu chí NA và NE không tính vào.
2. **Điểm toàn ca** = trung bình có trọng số của 5 hoạt động, trọng số lấy theo brief:
   - Chào hỏi: 10%;
   - Khởi động: 10%;
   - Học riêng cùng con: 35%;
   - Học cùng gia đình: 20%;
   - Trao đổi riêng với phụ huynh: 25%.

   Ví dụ, một buổi có 5 hoạt động đạt 70 / 100 / 69 / 64 / 75 thì điểm toàn ca bằng 7 + 10 + 24,2 + 12,8 + 18,8 ≈ **72,8%**.
3. **Xếp loại:**
   - **Tuân thủ tốt (follow kịch bản):** từ 80% trở lên, theo yêu cầu nhận ngày 12/10.
   - **Chệch kịch bản (dưới chuẩn):** dưới 80%. Các ca này hiện trong danh sách "Ca dưới chuẩn" trên dashboard, kèm link xem chi tiết.
   - **Thiếu dữ liệu:** hơn 30% số tiêu chí là NE, hoặc bản ghi không dùng được. Những ca này được ghi riêng, không tính là 0%.

Điểm do công thức tính, không do AI tự cộng. Vì vậy khi PDC đổi ngưỡng hay trọng số, có thể tính lại toàn bộ các ca cũ ngay mà không cần chấm lại.

## 5. Các lớp chống sai

| Rủi ro | Cách xử lý |
|---|---|
| AI bịa dẫn chứng | Mọi câu trích dẫn được đối chiếu với bản ghi. Câu không có thật thì không đưa vào email, và tiêu chí đó bị hạ về "Thiếu dữ liệu". Ở 2 buổi thử (lượt chấm mới nhất), 433/444 trích dẫn khớp nguyên văn, 6 khớp gần đúng, 1 không tìm thấy |
| AI đọc sai nghĩa khi trích gần đúng | Chỉ chấp nhận trích gần đúng khi không lệch ở chữ phủ định ("không", "chưa"...) hay chữ số. Email luôn in câu gốc trong bản ghi |
| Mỗi lần chấm một khác | Chấm 3 lần độc lập rồi lấy đa số. Ba lần cho ba kết quả khác nhau thì **lấy mức thấp hơn**. Trang chi tiết đánh dấu những tiêu chí dao động |
| Gán nhầm ai đang nói | Hệ thống tự phát hiện khi nhãn Phụ huynh / Học sinh bị đảo, dựa vào cách xưng hô ("dạ con", "cô ơi" so với "chị thấy", "bé nhà chị"), rồi đổi lại và ghi cảnh báo |
| Lộ thông tin gia đình | Che số điện thoại và số tài khoản trước khi gửi AI. Chỉ dùng AI qua tài khoản Google Cloud của công ty. Bảng điều khiển không có tên Mentor và mã ca được mã hóa. Email và trang chi tiết có trích lời gia đình nên chỉ người có quyền được xem |
| Mentor làm đúng kịch bản nhưng bị gắn cờ "gây áp lực" | Cờ được đánh dấu **"hành vi này có trong kịch bản"**, và email ghi là đang chờ Học thuật xem lại cách đánh giá (mục 7, câu 1) |

## 6. Kết quả chạy thử trên 2 buổi thật (11/10/2026)

AI chấm, **chưa có người chấm đối chiếu**:

| | Buổi A (128 phút) | Buổi B (64 phút) |
|---|---|---|
| Điểm toàn ca | 70,2%: Chệch kịch bản | 72,8%: Chệch kịch bản |
| Hoạt động thấp nhất | Học cùng gia đình (64%) | Học cùng gia đình (64%) |
| Lỗi chung của cả 2 buổi | Không khai thác kết quả WCA khi trao đổi với phụ huynh (OB31, LK04) | Như buổi A |
| Cờ hành vi | Độc thoại nhiều; gây áp lực (có trong kịch bản) | Độc thoại nhiều; gây áp lực (có trong kịch bản); không chốt bước tiếp theo |

**Những gì đã học được:**

1. **Hệ thống phân vai cần chỉnh riêng cho buổi onboarding.** Lần đầu, hệ thống gán ngược vai Phụ huynh và Học sinh, vì nó được thiết kế cho buổi 1:1 hàng tuần (chỉ có Mentor và con). Lỗi này làm AI kết luận sai rằng một buổi "lệch thứ tự nghiêm trọng". Lỗi đã được sửa. Vẫn còn vài câu lẻ bị gộp nhầm khi phụ huynh và con ngồi chung một máy, nhưng ảnh hưởng tới điểm dưới 2 điểm %.
2. **Điểm còn dao động.** Buổi B chấm 3 lượt ra 65,0% / 61,8% / 72,8%. Trong khi đó nghiệm thu yêu cầu lệch so với người chấm không quá ±5 điểm %. Những tiêu chí dao động nhiều nhất thường là những tiêu chí mà ranh giới giữa "làm đủ" và "làm một phần" chưa rõ (mục 7, câu 4).
3. **Buổi A dài 128 phút**, gấp đôi thời lượng tham chiếu. Phần trao đổi riêng với phụ huynh chiếm khoảng 80 phút.

## 7. Cần PDC góp ý hoặc quyết định

**Câu 1: Chấm phần bán hàng thế nào khi kịch bản và brief khác nhau?**
- Kịch bản dạy: "offer hết hạn rất nhanh, cần quyết định ngay", "đăng ký từ hôm nay để giữ ưu đãi 47%, sau 7 ngày là hết", "đợi PH thực sự nói vâng".
- Brief yêu cầu gắn cờ "gây áp lực hoặc suy diễn sự đồng ý" (cờ 9) và không chấm cao hành vi gây áp lực.
- Cả 2 buổi thử đều bị gắn cờ 9 vì Mentor làm đúng kịch bản. PDC chọn một trong ba hướng:
  - **(a)** Vẫn gắn cờ, giữ ghi chú "có trong kịch bản" như hiện nay.
  - **(b)** Không gắn cờ khi Mentor nói đúng như kịch bản.
  - **(c)** Sửa kịch bản.

**Câu 2: Các ngưỡng.**
- "Tuân thủ tốt" đã chốt từ 80% (yêu cầu nhận 12/10). PDC xác nhận lại nếu khác.
- "Thiếu dữ liệu" có giữ mức hơn 30% số tiêu chí không đủ bằng chứng không?

**Câu 3: Buổi kéo dài.** Buổi 128 phút có cần nhắc trong góp ý không? Thời lượng hoạt động 5 (brief ghi "20–25 phút, cần thống nhất lại") nên là bao nhiêu?

**Câu 4: Làm rõ ranh giới "làm đủ" và "làm một phần"** ở các tiêu chí AI hay dao động: OB01, OB13, OB27, OB28, OB35, OB36. Ví dụ OB27 (check-out cảm xúc) gồm 5 việc. Mentor làm 3 trên 5 thì là "làm một phần", hay chỉ cần hỏi cảm xúc của cả hai người là đủ? Mỗi tiêu chí chỉ cần một câu quy tắc như vậy là AI ổn định hơn rõ.

**Câu 5: Bản đầy đủ của kịch bản.** Hiện hệ thống mới có phần "logic script". Full script ở thẻ thứ 2 của tài liệu chưa được đưa vào. Có bản đầy đủ thì AI đối chiếu từng bước chính xác hơn.

**Câu 6: Bộ 5 buổi đối chiếu (điều kiện nghiệm thu giai đoạn 1).**
- Mỗi buổi, chuyên viên chấm tay độc lập 37 tiêu chí, 6 liên kết và 10 cờ theo phiếu mẫu (bảng tính, mỗi dòng một mục).
- Chuyên viên đánh giá từng góp ý của AI là phù hợp hay không phù hợp. Đây là chỉ tiêu "từ 80% góp ý phù hợp" trong v3.0.
- Ước tính khoảng 1–1,5 giờ chấm cho mỗi buổi.

**Câu 7: Người nhận và quyền xem.**
- Email gửi thẳng Mentor, hay qua Học thuật duyệt trước trong giai đoạn đầu?
- Những ai được mở trang chi tiết có trích lời gia đình?

## 8. Cách góp ý

- **Cách góp ý:** ghi trực tiếp vào tài liệu này hoặc gửi qua anh Phong. Góp ý về tiêu chí xin ghi kèm **mã tiêu chí** và **một ví dụ câu nói** cụ thể.
- **Cách áp dụng:** mỗi thay đổi về tiêu chí hay ngưỡng sẽ được chạy lại trên cùng bộ buổi đã có, để so trước và sau bằng số liệu, không chỉnh theo cảm tính.
- **Để PDC xem kết quả:** khi cần, Tuấn Anh gửi trang chi tiết và email mẫu của 2 buổi thử qua kênh nội bộ, vì các file này có trích lời gia đình.
