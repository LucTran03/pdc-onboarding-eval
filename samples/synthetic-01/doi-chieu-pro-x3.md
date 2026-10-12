# Đối chiếu AI với người chấm

## Ca synthetic-01-x3

| Chỉ tiêu | Kết quả | Mục tiêu | |
|---|---|---|---|
| Phân loại tiêu chí trùng người chấm | 92% (chấp nhận thêm: 95%) | ≥ 85% | ĐẠT |
| Lệch tỷ lệ tuân thủ toàn ca | AI 85% · người 81% · lệch 3.8 điểm % | ≤ 5 | ĐẠT |
| Tìm đúng lỗi (NF/PF của người chấm) | 80% · độ chính xác 100% | ≥ 85% | CHƯA |
| Logic liên kết trùng | 67% | ≥ 80% | CHƯA |
| Tiêu chí NF có dẫn chứng đã xác minh | 100% | 100% | ĐẠT |
| Cờ hành vi | recall 100% · precision 100% | — | |

| Mã | Bước | Người chấm | AI | Trùng |
|---|---|---|---|---|
| OB01 | Chào hỏi và thiết lập kết nối | FF | FF | ✓ |
| OB02 | Giới thiệu Mentor và xây dựng sự tin tưởng | FF | FF | ✓ |
| OB03 | Giới thiệu giá trị và nội quy TeenCare | FF | FF | ✓ |
| OB04 | Xác nhận cam kết học tập | FF | FF | ✓ |
| OB05 | Giới thiệu lịch trình buổi học | FF | FF | ✓ |
| OB06 | Thực hiện thử thách 2–3 từ khóa | FF | FF | ✓ |
| OB07 | Giao nhiệm vụ riêng cho phụ huynh | FF | FF | ✓ |
| OB08 | Xác nhận không gian riêng tư và cảm xúc của con | NF/PF | NF | ✓ |
| OB09 | Khám phá sở thích cá nhân | PF | PF | ✓ |
| OB10 | Khám phá niềm tự hào về bản thân | FF | FF | ✓ |
| OB11 | Khám phá nỗi sợ, nỗi buồn hoặc những điều khó chia sẻ | FF | FF | ✓ |
| OB12 | Củng cố thông điệp lắng nghe và tin tưởng bản thân | FF | FF | ✓ |
| OB13 | Giải thích sức mạnh của thói quen | FF | FF | ✓ |
| OB14 | Sử dụng câu chuyện minh họa | NE | NE | ✓ |
| OB15 | Xác định mục tiêu cá nhân | FF | FF | ✓ |
| OB16 | Kết nối với định hướng Thân – Tâm – Trí | FF | FF | ✓ |
| OB17 | Xây dựng sự sẵn sàng tham gia học tập | FF | FF | ✓ |
| OB18 | Thống nhất lịch học ba lớp | NF | NF | ✓ |
| OB19 | Giao thử thách hình thành thói quen | FF | FF | ✓ |
| OB20 | Chuẩn bị chuyển tiếp sang phần gia đình | FF | FF | ✓ |
| OB21 | Tóm tắt kết quả buổi học riêng | FF | FF | ✓ |
| OB22 | Củng cố tinh thần đồng hành và nội quy | FF | FF | ✓ |
| OB23 | Giới thiệu vai trò và tạo không khí | FF | FF | ✓ |
| OB24 | Hoạt động nhìn lại ký ức và chia sẻ từ khóa | PF | PF | ✓ |
| OB25 | Hoạt động chia sẻ cảm xúc khó nói | FF | FF | ✓ |
| OB26 | Hoạt động ghi nhận và cảm ơn | FF | FF | ✓ |
| OB27 | Check-out cảm xúc và kết thúc hoạt động | FF | FF | ✓ |
| OB28 | Nhắc lại nội dung buổi khai giảng | FF | FF | ✓ |
| OB29 | Khai thác lý do gia đình lựa chọn TeenCare | PF | PF | ✓ |
| OB30 | Đưa ra nhận định sư phạm về học sinh | FF | FF | ✓ |
| OB31 | Khai thác kết quả WCA và nhu cầu xây dựng thói quen | NF | NF | ✓ |
| OB32 | Giới thiệu mô hình TeenCare | PF | FF | ✗ |
| OB33 | So sánh các chương trình Học tập và Huấn luyện | FF | FF | ✓ |
| OB34 | Giải thích chi phí và điều kiện đăng ký | PF | FF | ✗ |
| OB35 | Lắng nghe và giải quyết băn khoăn | PF | PF | ✓ |
| OB36 | Xác nhận lựa chọn và bước tiếp theo | NF/PF | PF | ≈ |
| OB37 | Hướng dẫn phụ huynh đồng hành cùng con | FF | FF | ✓ |
| LK01 | Từ khóa đầu buổi → Chim sẻ gọi Đại bàng | CHUA_DAT | CHUA_DAT | ✓ |
| LK02 | Check-in và khám phá bản thân → Nhận định sư phạm | DAT | DAT | ✓ |
| LK03 | Mục tiêu của con → Thói quen và lịch học | DAT | DAT_MOT_PHAN | ✗ |
| LK04 | WCA → Phân tích nhu cầu gia đình | CHUA_DAT | CHUA_DAT | ✓ |
| LK05 | Khó khăn của gia đình → Giải pháp được tư vấn | CHUA_DAT | CHUA_DAT | ✓ |
| LK06 | Cam kết và lịch học → Hành động sau buổi onboarding | CHUA_DAT | DAT_MOT_PHAN | ✗ |
