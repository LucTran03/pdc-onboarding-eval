# Prompt chấm onboarding — cách dùng, model, tính điểm

> Cập nhật: 2026-10-09 · Trạng thái: draft v0.2 (đã chạy thật trên ca giả qua tool [`../tool/`](../README.md)) · Nguồn: [`../README.md`](../docs/yeu-cau-pdc.md) (yêu cầu PDC), [`../kha-thi-2026-10-09.md`](../docs/kha-thi-2026-10-09.md)

## 1. Các file

| File | Vai trò |
|---|---|
| [`system_prompt.md`](system_prompt.md) | System instruction gửi nguyên văn (bỏ comment đầu file) |
| [`criteria.json`](criteria.json) | Danh mục chuẩn: 5 hoạt động + trọng số, 37 tiêu chí OB, 6 LK, 10 cờ F. Sinh tự động từ brief PDC; brief đổi thì sinh lại. Mỗi tiêu chí có thêm `goal` (mục tiêu cấu phần) + `signals` (dấu hiệu đạt) — model chấm theo mức đạt mục tiêu, không theo câu chữ. `goal`/`signals` là bản nháp 14/10 **chờ PDC duyệt**; sinh lại từ brief thì phải giữ hai trường này |
| [`output_schema.json`](output_schema.json) | Schema JSON model phải trả về |

## 2. Ghép nội dung gửi model (phần user)

```
<BASELINE>
{criteria.json}
</BASELINE>

<SCRIPT_REFERENCE>
{090426_SEC_Script_Onboarding.txt, đọc từ data/raw/ hoặc OBEVAL_SCRIPT}
</SCRIPT_REFERENCE>

<SESSION_META>
ngày buổi học: …; thời lượng recording: …; nguồn transcript: meet|stt|gemini_audio;
ghi chú nhãn người nói: …
</SESSION_META>

<TRANSCRIPT>
[00:03:37] Tên người nói: lời thoại…
</TRANSCRIPT>
```

Mỗi dòng transcript cần mốc giờ. Nhãn người nói giữ nguyên như nguồn; không có nhãn thì để trống.

## 3. Model đề xuất (Vertex AI)

| Vai trò | Model | Lý do |
|---|---|---|
| **Chấm chính** | `gemini-2.5-pro` | Phải suy luận trên cả buổi 60–80 phút, nối thông tin xuyên hoạt động (LK01–LK06), trích dẫn chính xác bằng tiếng Việt và trả JSON dài |
| So sánh giá rẻ | `gemini-2.5-flash` | Chạy cùng bộ 5 video giai đoạn 1. Nếu đạt ngưỡng nghiệm thu như Pro thì dùng Flash để giảm ~4 lần chi phí |
| Thử sau | Model Gemini mới hơn | Chỉ khi org policy `vertexai.allowedModels` của project mở (đang chờ ops) |

**Cấu hình đề xuất:**
- `temperature = 0`;
- `response_mime_type = application/json` + `response_json_schema`;
- `max_output_tokens = 32768`;
- thinking budget khoảng 8.192–16.384.

Chạy trong project GCP của công ty, **không dùng key Gemini cá nhân** (dữ liệu trẻ em). Trước khi chạy cần kiểm model có trong `vertexai.allowedModels` và còn quota.

**Chi phí ước (chưa đo):** input ~45 nghìn token (danh mục ~8k + kịch bản ~17k + transcript 60 phút ~20k), output + thinking ~25 nghìn token.

| Model | Ước tính / buổi |
|---|---|
| Pro | ~0,3 USD |
| Flash | ~0,08 USD |

**Đo thật 09/10 (ca giả `synthetic-01`, 48 phút, 5.736 từ, Gemini 2.5 Pro):**
- 36.103 token prompt, 11.158 token output, 6.060 token thinking;
- **0,22 USD**, 137 giây.

**Giới hạn của Vertex `response_json_schema`:** schema có `minItems/maxItems = 37` bị từ chối với lỗi "too many states for serving". Tool bỏ các ràng buộc độ dài khi gửi API, rồi tự kiểm đủ 37/6/≤ 3 ở bước hậu xử lý.

## 4. Hậu xử lý (code làm, không để model làm)

1. **Kiểm JSON:** đúng schema, đủ 37 OB và 6 LK, không trùng mã.
2. **Kiểm trích dẫn:** mỗi `quote` phải có nguyên văn trong transcript (so sau khi chuẩn hoá khoảng trắng, dấu câu, hoa thường).
   - Trích dẫn không khớp → đánh dấu `quote_unverified`.
   - Tiêu chí có toàn bộ bằng chứng không khớp → hạ về `NE` và ghi vào danh sách lỗi của AI (phục vụ nghiệm thu "100% lỗi quan trọng có dẫn chứng").
3. **Tính điểm:**
   - FF = 1; PF = 0,5; NF = 0; NA và NE không tính vào mẫu số.
   - Điểm hoạt động = trung bình các tiêu chí còn lại trong hoạt động đó.
   - Điểm toàn ca = Σ (trọng số × điểm hoạt động) / Σ trọng số của các hoạt động có dữ liệu.
   - Báo kèm **tỷ lệ tiêu chí NE**. Nếu > 30% (ngưỡng đề xuất, cần PDC chốt) hoặc `insufficient_data = true` → ca **"thiếu dữ liệu"**, không tính vào thống kê "tuân thủ tốt / chệch".
4. **Đổi mã sang tên tiếng Việt** (lấy từ `criteria.json`) khi dựng báo cáo, theo yêu cầu "không chỉ hiển thị mã OB29".
5. **Cờ có `script_instructed = true`** hiển thị riêng ("hành vi theo kịch bản nhưng bị brief gắn cờ") cho tới khi PDC chốt cách xử lý.

## 5. Còn chờ

- PDC chốt mâu thuẫn kịch bản và brief ở phần bán hàng (OB33–OB36, cờ F09).
- PDC chốt ngưỡng "ca tuân thủ tốt" (đầu ra v3.0 gợi ý 85%) và ngưỡng "thiếu dữ liệu".
- 5 video kèm bảng chấm tay của học thuật để đo độ trùng (giai đoạn 1).
