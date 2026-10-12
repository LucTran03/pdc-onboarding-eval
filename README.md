# pdc-onboarding-eval — AI chấm buổi onboarding TeenCare

> Cập nhật: 2026-10-12 · Trạng thái: prototype (bàn giao cho Tuấn Anh) · Nguồn: brief PDC "Onboarding Evaluation_AI Brief" + "TeenCare_Outcomes AI Agent" v3.0 · Bàn giao: [`HANDOFF.md`](HANDOFF.md)

Tool chấm một buổi onboarding (Mentor + phụ huynh + học sinh) từ transcript:
- 37 tiêu chí theo 5 hoạt động, có trọng số;
- 6 logic liên kết, 10 cờ hành vi, chấm cả thứ tự các bước.

Tool xuất 2 đầu ra:
- **email góp ý riêng cho Mentor** (bản nháp `.eml`, không tự gửi);
- **bảng điều khiển tổng hợp** cho học thuật: không tên Mentor, không lời thoại.

Có thêm phần đối chiếu AI với người chấm, dùng để nghiệm thu giai đoạn 1.

## Cài đặt

```bash
python -m venv .venv && .venv/Scripts/activate        # Python ≥ 3.10
pip install -r requirements.txt
```

**Credential Vertex AI** (chỉ dùng project GCP của công ty, không dùng key Gemini cá nhân vì là dữ liệu trẻ em). Chọn một trong hai:
- `set GOOGLE_APPLICATION_CREDENTIALS=<đường dẫn service account JSON>`;
- `gcloud auth application-default login`.

Kiểm model có dùng được không (chỉ đọc metadata, không tốn tiền):

```bash
python run.py check-vertex --model gemini-2.5-pro
```

**Kịch bản PDC** (`090426_SEC_Script_Onboarding.txt`) **không có trong repo**, vì kịch bản có số tài khoản ngân hàng. Xin anh Lực hoặc PDC, rồi đặt vào `data/raw/` (hoặc trỏ `OBEVAL_SCRIPT`).

## Chạy

```bash
python run.py run data/in/<transcript>.json --session-date 2025-10-28 --mentor-name "Thầy/Cô <tên>" --mentor-label SPEAKER_00
python run.py batch data/in                          # mọi transcript trong thư mục
python run.py run <file> --dry-run                   # chỉ dựng prompt, không gọi model
python run.py rescore data/out/<ca>                  # tính lại từ câu trả lời đã lưu, không gọi model
python run.py dashboard                              # dựng lại data/out/dashboard.html
python run.py human-template data/phieu-cham-tay.csv # phiếu cho học thuật chấm tay
python run.py compare --ai data/out/<ca> --human <phiếu>.csv --out doi-chieu.md
```

- Mặc định mỗi ca chấm **3 lần song song** (Gemini 2.5 Pro, temperature 1.0, seed khác nhau) rồi lấy đa số. Chi phí khoảng 0,7 USD và 3 phút mỗi ca. Thử nhanh thì thêm `--runs 1`.
- Kết quả mỗi ca nằm trong `data/out/<ngày>_<tên file>_<băm>/`:
  - `email_mentor.html` / `.eml`;
  - `detail.html` (trang kiểm định: 37 tiêu chí, trích dẫn ✓/✗, độ ổn định giữa các lần chấm);
  - `result.json`, `model_raw.json`;
  - `dashboard_row.json`, `status.json`.

### Định dạng transcript đọc được (tự nhận)

| Nguồn | Ví dụ |
|---|---|
| STT có tách người nói | `{"segments":[{"start":3.2,"end":9.8,"speaker":"SPEAKER_00","text":"..."}]}` (nhận cả `start_ms`, `speaker_label`, `utterances`) |
| File GCS `transcripts/<sid>.json` | `{"transcript":"...","segments":[...]}` |
| Hàng bảng `transcripts` (DB TeenCareParent) | `{"transcript":[{"text":..,"start_time":-1}]}` — không mốc giờ thì dùng số dòng `#0001` |
| Google Meet transcript (.txt) | dòng `00:05:00`, rồi `Tên: lời` |
| Văn bản có mốc giờ / SRT / VTT | `[00:03:37] Mentor: …` · `00:00:01,000 --> …` |

### Biến môi trường

| Biến | Mặc định |
|---|---|
| `OBEVAL_DATA_ROOT` | `./data` (hoặc `D:/teencare-data/pdc-onboarding` nếu tồn tại) |
| `OBEVAL_SCRIPT` · `OBEVAL_OUT_ROOT` | `<data>/raw/090426_SEC_Script_Onboarding.txt` · `<data>/out` |
| `OBEVAL_GCP_PROJECT` · `OBEVAL_GCP_LOCATION` | `tcservices2027` · `us-central1` |
| `OBEVAL_MODEL` · `OBEVAL_RUNS` · `OBEVAL_THINKING` | `gemini-2.5-pro` · `3` · `16384` |
| `OBEVAL_GOOD_THRESHOLD` · `OBEVAL_NE_RATIO` | `0.85` · `0.30` (PDC chưa chốt) |

## Kiểm tra

```bash
python -m unittest discover -s tests      # 60 test, không gọi model
```

## Cấu trúc

| Đường dẫn | Nội dung |
|---|---|
| `obeval/transcript.py` | Đọc mọi định dạng, chuẩn hoá chữ, che SĐT / số tài khoản (`[SỐ]`) |
| `obeval/prompt.py` · `prompt/` | System prompt, danh mục tiêu chí (`criteria.json`), schema đầu ra |
| `obeval/llm.py` | Gọi Gemini trên Vertex AI (schema JSON, thinking, thử lại) |
| `obeval/validate.py` | Kiểm schema, vá chỗ thiếu thành `NE` (không bịa) |
| `obeval/verify.py` | Mọi trích dẫn phải có trong transcript; sửa mốc giờ; hạ nhận định không có căn cứ |
| `obeval/ensemble.py` | Gộp N lần chấm (đa số / trung vị), đo độ ổn định |
| `obeval/score.py` | Tính điểm bằng code: FF=1, PF=0,5, NF=0, NA/NE loại khỏi mẫu số |
| `obeval/report.py` · `dashboard.py` | Email Mentor, trang chi tiết, bảng điều khiển |
| `obeval/compare.py` | Đối chiếu AI với người chấm (chỉ tiêu nghiệm thu v3.0) |
| `samples/synthetic-01/` | Buổi giả 48 phút (nhân vật hư cấu) + đáp án + kết quả đối chiếu |
| `docs/` | Yêu cầu PDC, khả thi (luồng Drive → STT → chấm), 3 vòng review độc lập |
