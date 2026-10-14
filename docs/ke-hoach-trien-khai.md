# Kế hoạch triển khai AI chấm buổi onboarding

> Cập nhật: 13/10/2026 · Người viết: Tuấn Anh · Trạng thái: đã chạy thử trên máy với 2 ca thật, chưa tự động

## 1. Mục tiêu

Mỗi buổi onboarding (Mentor 1:1 Onboard) kết thúc thì **tự động**, không ai phải thao tác tay:

1. Có transcript chia người nói (Mentor / Phụ huynh / Học sinh).
2. AI chấm theo kịch bản SEC Onboarding (37 bước, 5 hoạt động), ra **% follow kịch bản**.
3. Mentor nhận báo cáo ngắn ngay sau ca: % follow, phần chưa follow, cần cải thiện gì cho lần sau (hiện trong trang Lịch đã đặt của TeenCareBooking, không gửi email).
4. PDC xem dashboard tổng (Data Analyst dựng, đọc thẳng từ DB, không thuộc pipeline): tổng số ca, % follow, % ca đạt / không đạt (ngưỡng 80%), danh sách ca dưới chuẩn kèm link, các phần hay sai nhất.

## 2. Đã làm được

| Hạng mục | Kết quả |
|---|---|
| Nối STT chia người nói vào bộ chấm | Xong, chạy trên máy cá nhân. Đã sửa lỗi STT nhận nhầm Phụ huynh ↔ Học sinh |
| Chạy thử 2 ca thật | 70,2% và 72,8%; báo cáo Mentor có mốc giờ từng hoạt động |
| Nơi lưu kết quả | 5 bảng trên DB đặt lịch **dev**, đã ghi 2 ca thử |
| Báo cáo Mentor trong TeenCareBooking | Đã code, đã đẩy nhánh `tanh/dev/onboarding-ai-report`; Mentor chỉ thấy buổi của mình |

**Còn thiếu để chạy thật:** toàn bộ phần tự động hoá — chính là 3 bước của kế hoạch dưới đây.

## 3. Luồng hiện tại và chỗ phải thêm

### 3.1. Buổi 1:1 hàng tuần đang chạy thế nào (đã đối chiếu code 13/10)

```
Meet ghi hình → file mp4 trên Drive
  → Apps Script (Nhật Anh) gom recording vào folder chung
  → session-on-trigger  POST /v1/sessions/drive-webhook                       [Cloud Run]
       đọc mã TC + giờ trong TÊN FILE → tìm buổi trong bảng sessions (CRMxLMS), lệch ≤ 90 phút
  → Cloud Tasks → session-data-worker  POST /v2/tasks/phase1                  [Cloud Run]
       {session_id, student_id, gcs_uri = link Drive, timestamp, lang}
  → temp-transcript  POST /beta/transcript                                    [Cloud Run]
       stream mp4 từ Drive → mp3 16k → gs://teenup-transcripts/temp_beta/…
       → STT  POST /v1/transcribe {gcs_uri, session_id, student_id, callback_url, language}
  → STT trên server GPU: Redis → worker → gs://teenup-transcripts/transcripts/<session_id>.json
       → callback về temp-transcript
  → session-data-worker hỏi lại (5 phút/lần, tối đa 12 lần) → nhận transcript dạng CHỮ
  → lưu bảng transcripts → mentor report, QA, insight, VPP, parent coach
```

Các đường vào khác của session-on-trigger: `/webhook` (DB CRMxLMS bắn khi buổi chuyển `completed`, kèm hẹn fallback audio extension sau 4 giờ), `/livekit-webhook` (phòng học native), `/run` và `/sweep-missing-reports` (quét bù). Cả 4 đều xoay quanh bảng `sessions`.

### 3.2. Vì sao buổi onboarding chưa đi vào luồng này

| Chỗ | Hiện trạng | Hệ quả với onboarding |
|---|---|---|
| Apps Script | Chỉ gom recording 1:1 hàng tuần | Recording onboarding không vào folder |
| session-on-trigger | Tìm buổi trong `sessions` của CRMxLMS | Buổi onboarding chỉ có trong `bookings` của DB đặt lịch → không khớp, **bị bỏ im lặng** |
| session-data-worker | phase1 gắn chặt với `sessions`, `transcripts`, mentor report, VPP | Không có chỗ cho buổi không thuộc CRMxLMS |
| temp-transcript | Trả transcript dạng chữ; không có tham số chọn pipeline | Bộ chấm cần JSON có mốc giờ + vai người nói |
| STT | Pipeline chọn theo cấu hình **cả server** (`PIPELINE`); API chỉ nhận 5 trường kể trên | Không chỉ định được "job này chạy chia người nói, hồ sơ onboarding" |

**Điểm thuận lợi:** tên file recording onboarding có **cùng định dạng** với buổi hàng tuần (`TeenCare - Gia sư tâm lý 1_1 Onboarding -TC…_PH … - 2026_10_11 20_29 GMT+07_00 – Recording.mp4`). Bộ đọc mã TC + giờ của session-on-trigger dùng lại được; bảng `bookings` cũng có `student_code` và `start_at` để ghép.

### 3.3. Luồng đích cho onboarding (đi chung hạ tầng, tách nhánh riêng)

```
Recording onboarding (Drive)
  → Apps Script: nhận tên "…1_1 Onboarding…" → chuyển sang folder Onboarding riêng
       → gọi thẳng session-on-trigger 
  → session-on-trigger  POST /v1/onboarding/drive-webhook (mới)
       mã TC + giờ trong tên file → tìm booking onboarding trong DB đặt lịch → booking_id
  → Cloud Tasks → session-data-worker  POST /v2/tasks/onboarding (mới, mỏng)
  → temp-transcript  /beta/transcript  {session_id = booking_id, profile = "onboarding"}
  → STT: job này chạy pipeline chia người nói + luật gán vai onboarding
       → gs://teenup-transcripts/transcripts/<booking_id>.json   (đường dẫn như cũ)
  → session-data-worker thấy xong → gọi obeval
  → obeval [Cloud Run]: đọc thẳng JSON trên GCS → chấm → ghi DB đặt lịch (điểm cuối của pipeline)

DB đặt lịch ──► báo cáo Mentor trong TeenCareBooking
           └─► dashboard PDC (Data Analyst dựng, đọc thẳng DB)
```

## 4. Kế hoạch chi tiết

### Bước 1 — Apps Script: tách recording onboarding sang folder riêng và gọi session-on-trigger

| Việc | Chi tiết |
|---|---|
| Nhận diện buổi onboarding | Lọc tên chứa `1_1 Onboarding` (tên đang dùng: "Gia sư tâm lý 1:1 Onboarding"). Chốt với vận hành còn tên nào khác không |
| Chuyển file | Di chuyển sang folder Drive **Onboarding** riêng, không để lẫn với recording hàng tuần |
| Phân quyền folder | Chỉ service account của pipeline và nhóm PDC được đọc. Đây là video có trẻ vị thành niên |
| Gọi session-on-trigger | Ngay sau khi chuyển file, Apps Script gọi thẳng `POST /v1/onboarding/drive-webhook` với thông tin file (`id`, `name`, `webViewLink`, `createdTime) |
| Xác thực | Endpoint gọi từ Internet nên kèm khoá bí mật trong header, lưu ở Script Properties (không ghi trong code). Endpoint hàng tuần hiện chưa kiểm khoá; nhánh onboarding nên có ngay từ đầu |
| Gọi lỗi | session-on-trigger không trả 2xx thì Apps Script ghi lại file đó và gọi lại ở lượt chạy sau, không bỏ qua |

**Xong khi:** 1 tuần recording onboarding thật đều vào đúng folder và đều tới được session-on-trigger.

### Bước 2 — Pipeline onboarding (session-on-trigger, session-data-worker, temp-transcript, STT)

Nguyên tắc: **dùng lại hạ tầng có sẵn** (Cloud Tasks, cơ chế thử lại, callback, đường dẫn GCS), **không đụng luồng 1:1 hàng tuần** đang chạy cho khoảng 120 buổi/ngày. Mọi thay đổi là endpoint mới, hoặc tham số mới mà giá trị mặc định giữ nguyên hành vi cũ.

**2.1. session-on-trigger**
- Endpoint mới `POST /v1/onboarding/drive-webhook`. Dùng lại hàm đọc mã TC + giờ từ tên file và cửa sổ khớp 90 phút đã có.
- Tra `bookings` trong **DB đặt lịch** theo `student_code` + `start_at` + loại buổi onboarding. Cần thêm cấu hình và secret cho DB đặt lịch (service hiện chỉ có key CRMxLMS và TeenCareParent).
- Không khớp được thì **ghi rõ lý do và đưa vào danh sách xử lý tay**, không bỏ im lặng như nhánh hàng tuần từng gặp.
- Tạo Cloud Task tới session-data-worker, tên task theo `booking_id` để chống trùng.

**2.2. session-data-worker**
- Endpoint mới `POST /v2/tasks/onboarding` nhận `booking_id` + link Drive.
- Gọi temp-transcript với `session_id = booking_id`, `profile = onboarding`; chưa xong thì hẹn chạy lại (dùng lại cơ chế poll của phase1).
- Xong thì gọi obeval với đường dẫn `transcripts/<booking_id>.json`. **Không** ghi `transcripts` / `sessions`, **không** sinh mentor report, QA, VPP hay parent coach.
- Phương án gọn hơn để cân nhắc: bỏ bước này, session-on-trigger gửi thẳng task tới obeval và obeval tự gọi temp-transcript. Ít đụng vào service đang chạy prod hơn, nhưng lệch khỏi quy ước "mọi xử lý AI sau buổi đi qua session-data-worker".

**2.3. temp-transcript**
- Nhận thêm tham số `profile` (mặc định rỗng = như cũ), chuyển xuống STT khi gọi `/v1/transcribe`.
- Không cần đổi chỗ lưu: STT vẫn ghi `transcripts/<session_id>.json`, với onboarding thì `session_id` là `booking_id`. obeval đọc thẳng file JSON này (có mốc giờ và vai), không dùng bản chữ temp-transcript trả về.

**2.4. STT (server GPU) — phải build thêm luồng xử lý cho onboarding**

| Việc | Lý do |
|---|---|
| API Go + job Redis nhận thêm `profile` | Hiện API chỉ nhận `gcs_uri, session_id, student_id, callback_url, language` |
| Job onboarding **không được rơi về engine cũ** | Prod đã bật `PIPELINE=diarized` từ 12/10, nhưng khi hàng đợi > 5 job (`DIARIZED_MAX_BACKLOG`) thì tự chạy engine cũ, không có vai. 26 giờ qua có 29/210 job như vậy, toàn bộ rơi vào 20h–22h — đúng khung giờ có buổi onboarding. Job `profile = onboarding` phải luôn chạy pipeline chia người nói (chờ lâu hơn cũng được, bộ chấm không cần gấp) |
| Luật gán vai riêng cho onboarding | Luật hiện tại viết cho buổi 1:1 (Mentor + 1 học sinh). Onboarding có Mentor + Phụ huynh + Học sinh cùng lúc, nên STT đang nhận đảo Phụ huynh ↔ Học sinh. Đã vá tạm phía bộ chấm; cần sửa gốc trong STT |
| Lỗi pipeline → bản không vai | 2/210 job lỗi ở Sortformer (ONNX) và trả bản không vai. Bộ chấm đã nhận diện được trường hợp này (`stt_legacy_fallback`); với onboarding nên đánh dấu ca "thiếu dữ liệu" thay vì chấm |
| RAM / GPU | Đo 13/10: RAM 7,5 GB đã dùng 3,9 GB, **swap dùng 5,4/8 GB**; GPU 4,9/8 GB. Worker STT giới hạn 5 GB, đang dùng 3,8 GB. Job onboarding không thêm model mới (dùng chung pipeline đang chạy), nhưng server đã phải swap nhiều — liên quan đề xuất nâng cấp server |
| Xoá file tạm | Giữ quy tắc hiện tại: xoá mp3 sau khi transcribe; transcript onboarding giữ có thời hạn (đề xuất 90 ngày) |

**Xong khi:** recording onboarding thật đi hết từ Drive tới `transcripts/<booking_id>.json` có vai người nói, không cần thao tác tay; luồng 1:1 hàng tuần không đổi (so số buổi xử lý và thời gian chờ trước/sau).

### Bước 3 — Triển khai bộ chấm (obeval) và nối vào pipeline

**Chạy ở đâu:** **Cloud Run** trên GCP. GCS (bucket `teenup-transcripts`) chỉ là nơi lưu transcript, không chạy code. Không đặt trên server GPU vì:
- obeval không cần GPU (gọi Gemini qua Vertex), còn server GPU đang sát giới hạn RAM.
- Cloud Run tự cấp quyền Vertex qua service account riêng, không phải chép file key lên server.
- Không có ca thì không tốn tiền; nhiều ca cùng lúc thì tự mở thêm; một ca mất khoảng 3–4 phút, trong giới hạn của Cloud Run.

| Việc | Chi tiết |
|---|---|
| Đóng gói | Dockerfile + endpoint `POST /evaluate {booking_id, transcript_uri}` bọc quanh bộ chấm và lệnh ghi DB đã có |
| Quyền | Service account riêng: Vertex AI User, đọc `gs://teenup-transcripts/transcripts/` |
| Bí mật | Key DB đặt lịch đặt trong Secret Manager, không nằm trong code |
| Ghi DB **prod** | Tạo 5 bảng trên DB đặt lịch prod qua PR vào TeenCareBooking, chủ DB duyệt (hiện mới có trên dev) |
| Báo cáo trong TeenCareBooking | Merge nhánh `tanh/dev/onboarding-ai-report` |
| Dashboard PDC | Không thuộc pipeline: Data Analyst dựng trên Command Center, đọc thẳng DB theo `docs/data-cho-dashboard.md` |
| Theo dõi | Ca `error` / kẹt `processing` quá 24 giờ thì báo về kênh vận hành |



## 5. Lộ trình đề xuất

| Tuần | Việc | Ghi chú |
|---|---|---|
| 1 | Bước 1 (Apps Script) + bắt đầu Bước 2.4 (STT) | Phụ thuộc lịch Nhật Anh |
| 2 | Bước 2.1–2.3 + hoàn thiện STT | Thử trên môi trường dev / staging |
| 3 | Bước 3 + chạy **chế độ im lặng** | Chấm và lưu, Mentor chưa thấy (`published_at` để trống); PDC đối chiếu với chấm tay |

Thời gian là ước lượng, chưa tính thời gian chờ duyệt PR / quyền GCP.

## 6. Chi phí

| Khoản | Ước tính |
|---|---|
| Gemini 2.5 Pro (3 lần chấm/ca) | khoảng 0,5–0,8 USD/ca |
| Cloud Run, Cloud Tasks, GCS | gần như không đáng kể ở mức vài trăm ca/tháng |
| STT | chạy trên server GPU sẵn có; có thể cần nâng cấp RAM (xem đề xuất nâng cấp server) |

## 7. Rủi ro

| Rủi ro | Cách giảm |
|---|---|
| Làm chậm hoặc hỏng luồng 1:1 hàng tuần | Nhánh onboarding tách endpoint, tách prefix GCS; pipeline chọn theo từng job; so số liệu trước/sau khi bật |
| Server GPU tràn RAM | Đo trước khi bật; nạp model theo job; giới hạn 1 job onboarding cùng lúc |
| Ghép nhầm recording với booking | Chỉ chấm khi ghép chắc chắn; còn lại đưa vào danh sách xử lý tay |
| Mentor nhận góp ý sai | Chạy im lặng trước; Mentor có nút "góp ý chưa đúng" (bảng phản hồi đã có) |

