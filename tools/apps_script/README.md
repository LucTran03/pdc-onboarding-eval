# Apps Script: nhánh onboarding trong script đồng bộ recording

Script đồng bộ recording đang chạy (`syncMeetRecordings`, trigger 15 phút) do người khác giữ và **không nằm trong repo này**.
Thư mục này là bản lưu của phần thay đổi để thêm nhánh onboarding:

| File | Là gì |
|---|---|
| `onboarding.gs` | File mới, dán vào project Apps Script dưới dạng file riêng (cùng tên). Không chứa ID, URL hay token: đọc từ Script Properties. |
| `Code.gs` | Bản sao đã vệ sinh của `Code.gs` hiện tại, kèm các sửa đổi ở mục "Áp dụng lên script thật". Ba hằng số `PUBLIC_FOLDER_ID`, `WEBHOOK_URL`, `ALERT_EMAIL` là placeholder; giá trị thật chỉ nằm trong script đang chạy. **Không dán đè cả file này lên script thật.** |
| `../../tests/apps_script/test_apps_script.js` | Test Node với Drive/Properties/UrlFetch giả: `node tests/apps_script/test_apps_script.js` |

## Nhánh này làm gì

Cùng project, cùng tài khoản sở hữu recording, cùng khoá `LockService`. Buổi có **tên thư mục** khớp `ONBOARDING_PATTERN`
(`TeenCare - Gia sư tâm lý 1:1 Onboarding - TC…`) trong thư mục "Google Meet" đang dùng được chuyển sang một folder riêng
giới hạn quyền rồi báo cho `obeval`. Mọi thứ của onboarding tách khỏi luồng hàng tuần:

| | 1:1 hàng tuần (giữ nguyên) | Onboarding (mới) |
|---|---|---|
| Nhận diện (tên thư mục buổi) | `MEETING_PATTERN` | `ONBOARDING_PATTERN` |
| Chuyển tới | `Record` (`PUBLIC_FOLDER_ID`) | folder Onboarding giới hạn quyền (`ONBOARDING_FOLDER_ID`) |
| Hàng chờ (Script Property) | `PENDING_RECORDINGS` | `PENDING_ONBOARDING` |
| Gọi | `session-on-trigger /drive-webhook`, body là **mảng** file | `obeval POST /v1/recordings`, body là **một** object `{id,name,webViewLink,createdTime}`, header `X-Obeval-Token` |
| Cảnh báo | `ALERT_EMAIL` | `ONB_ALERT_EMAIL` |

Nhánh onboarding **tự tắt** (ghi log lỗi, không chuyển file nào) khi: thiếu Script Property bắt buộc, folder Onboarding đọc không được,
đang nằm trong thùng rác, hoặc **không ở chế độ `PRIVATE`** (danh sách cho phép: mọi kiểu `ANYONE`, `ANYONE_WITH_LINK`, `DOMAIN`,
`DOMAIN_WITH_LINK` hay giá trị lạ đều bị chặn). Ngoài ra, từng file chỉ được chuyển khi **bản thân file và thư mục đích của buổi họp
(tạo/lấy trong folder Onboarding) đều `PRIVATE`**; file không đạt thì nằm yên trong "Google Meet", không vào hàng chờ, log ghi id file
(không ghi tên). Nhánh hàng tuần không bị ảnh hưởng trong mọi trường hợp trên.

Khi nhánh tắt hoặc có file bị bỏ qua, script gửi **một mail** tới `ONB_ALERT_EMAIL` (nếu đặt), tối đa **1 lần / 24 giờ**
(mốc lưu ở Script Property `ONB_DISABLED_ALERT_AT`, ms epoch; xóa property này để gửi lại ngay). Mail nêu lý do, không có tên file, và nhắc:
recording đến trong lúc nhánh tắt vẫn nằm trong "Google Meet", chỉ được nhặt lại bằng `backfillOldRecordings` rồi `markRecentPendingOnboarding`
sau khi sửa xong. Lỗi gửi mail không bao giờ làm hỏng lượt chạy. Không có `ONB_ALERT_EMAIL` thì các danh sách "không khớp booking" /
"bị bỏ sau 2 ngày" được ghi `console.error` để vẫn thấy trong Executions.

## Script Properties (Project Settings > Script Properties)

| Khoá | Giá trị |
|---|---|
| `ONBOARDING_FOLDER_ID` | ID folder `Onboarding recordings` |
| `OBEVAL_URL` | URL gốc của obeval, không có `/v1/recordings` (dùng `obeval-dev` khi thử, `obeval` prod sau) |
| `OBEVAL_TOKEN` | giá trị secret `obeval-api-token` |
| `ONB_ALERT_EMAIL` | mail nhận cảnh báo onboarding (thiếu thì vẫn chạy, chỉ ghi log thay vì gửi mail) |

Script tự ghi thêm `PENDING_ONBOARDING` (hàng chờ) và `ONB_DISABLED_ALERT_AT` (mốc chống spam mail): không cần đặt tay.

## Yêu cầu với folder Onboarding

Video là của trẻ vị thành niên, nên:

- Tạo folder `Onboarding recordings` cạnh `Record`, bằng **tài khoản chạy script**.
- Chia sẻ **chỉ** cho service account của `temp-transcript` (Viewer) và nhóm PDC.
- **Không** bật "ai có link" và cũng không bật chia sẻ cả domain: folder phải ở chế độ `PRIVATE` (chỉ người được thêm đích danh).
  Script kiểm tra mỗi lượt chạy và không chuyển file nếu không đúng (xem mục trên). Thư mục con của từng buổi và chính file cũng phải `PRIVATE`.
  Lưu ý: nếu domain Workspace mặc định chia sẻ recording trong cả domain thì file sẽ bị bỏ qua và bạn sẽ nhận mail cảnh báo.
- Recording onboarding phải nằm trong thư mục "Google Meet" của chính tài khoản chạy script (`'me' in owners`).
  Nếu buổi do tài khoản khác tổ chức thì script này không thấy: dừng lại và báo, phải chạy script ở tài khoản đó.

## Áp dụng lên script thật

1. Sao lưu `Code.gs` đang chạy ra ngoài git trước (xem mục thử bên dưới).
2. Thêm file mới `onboarding` (`onboarding.gs`) vào project: dán nguyên nội dung. **Làm bước này TRƯỚC bước 3**: nếu sửa `Code.gs` trước,
   mỗi lượt chạy hàng tuần sẽ báo `ReferenceError: sendPendingOnboarding is not defined` ở cuối lượt.
3. Trong `Code.gs` thật, **chỉ** sửa các chỗ sau (giữ nguyên ba hằng số thật). Bản dạng diff:

```diff
 function syncMeetRecordings() {
   ...
     scanAndMove(Date.now() - LOOKBACK_HOURS * HOUR_MS);
     sendPending();
+    sendPendingOnboarding();
   } finally {

 function backfillOldRecordings() {
   scanAndMove(Date.now() - 180 * DAY_MS);
   sendPending();
+  sendPendingOnboarding();
 }

 // trong scanAndMove
-  const meetingNames = new Map(); // id thư mục buổi họp -> tên nếu cần chuyển, '' nếu bỏ qua
+  const meetingNames = new Map(); // id thư mục buổi họp -> {name, kind}; kind = 'weekly' | 'onboarding' | '' (bỏ qua)
 ...
       if (!meetingNames.has(meetingId)) {
         const root = firstParent(meeting);
         const name = meeting.getName();
-        const wanted = root !== null && activeRoots.has(root.getId()) && MEETING_PATTERN.test(name.normalize('NFC'));
-        meetingNames.set(meetingId, wanted ? name : '');
+        const active = root !== null && activeRoots.has(root.getId());
+        const kind = !active ? ''
+          : MEETING_PATTERN.test(name.normalize('NFC')) ? 'weekly'
+          : isOnboardingMeeting(name) ? 'onboarding' : '';
+        meetingNames.set(meetingId, {name: name, kind: kind});
       }
-      const name = meetingNames.get(meetingId);
-      if (!name) continue;
+      const m = meetingNames.get(meetingId);
+      if (!m.kind) continue;
+      const onboarding = m.kind === 'onboarding';
+      let onbDest = null;
+      if (onboarding) {
+        onbDest = onboardingDestination_(video, m.name);
+        if (!onbDest) continue;
+      }
 
       // Đánh dấu TRƯỚC khi chuyển: ...
       if (video.getDateCreated().getTime() > sendCutoff) {
         video.setDescription(MARK_PENDING);
-        addPending(video.getId());
+        addPending(video.getId(), onboarding ? ONB_PENDING_KEY : PENDING_KEY);
       }
-      video.moveTo(getOrCreateFolder(publicRoot, name));
-      console.log('Đã chuyển: ' + name + ' / ' + video.getName());
+      video.moveTo(onboarding ? onbDest : getOrCreateFolder(publicRoot, m.name));
+      console.log('Đã chuyển' + (onboarding ? ' (onboarding)' : '') + ': ' + m.name + ' / ' + video.getName());

-function getPending() {
-  return JSON.parse(PropertiesService.getScriptProperties().getProperty(PENDING_KEY) || '{}');
+function getPending(key) {
+  return JSON.parse(PropertiesService.getScriptProperties().getProperty(key || PENDING_KEY) || '{}');
 }
-function setPending(pending) {
-  PropertiesService.getScriptProperties().setProperty(PENDING_KEY, JSON.stringify(pending));
+function setPending(pending, key) {
+  PropertiesService.getScriptProperties().setProperty(key || PENDING_KEY, JSON.stringify(pending));
 }
-function addPending(id) {
-  const pending = getPending();
+function addPending(id, key) {
+  const pending = getPending(key);
   if (!(id in pending)) {
     pending[id] = Date.now();
-    setPending(pending);
+    setPending(pending, key);
   }
 }
```

**`backfillOldRecordings` (chạy tay) quét 180 ngày:** nó sẽ chuyển tới 180 ngày recording onboarding còn nằm trong "Google Meet"
vào folder Onboarding (chỉ chuyển; file cũ hơn 2 ngày không vào hàng chờ nên không gửi gì cho obeval). Chỉ chạy khi đã chắc folder Onboarding đúng quyền.

Với buổi hàng tuần, `kind = 'weekly'` và mọi lời gọi dùng đúng khoá, folder, log cũ; `isOnboardingMeeting` chỉ được gọi
cho thư mục KHÔNG khớp mẫu hàng tuần. Muốn chắc chắn, `diff` bản thật sau khi sửa với bản sao lưu: chỉ được có các thay đổi trên.

## Thử thủ công (trước khi để trigger chạy với onboarding)

1. Lưu bản sao `Code.gs` hiện tại ra **ngoài git** (vd. `D:\TeenCare\Plan\apps-script-backup-<ngày>.gs`) trước khi sửa.
2. Tắt tạm trigger `syncMeetRecordings`. Đặt `OBEVAL_URL` = `obeval-dev` (không để file thật bị gửi sang prod).
3. Chạy tay `syncMeetRecordings` và xem log (Executions):
   - file hàng tuần vẫn `Đã chuyển: …` sang `Record` và `Worker 200` như cũ;
   - file onboarding `Đã chuyển (onboarding): …` và `obeval 200: … → {"status":"queued"…}`
     (hoặc `unmatched` nếu booking không có trên DB dev, đó là hành vi đúng).
4. Chạy lại lần nữa: không file nào bị gửi lại (`PENDING_ONBOARDING` rỗng).
5. Thử chặn an toàn: tạm đổi `ONBOARDING_FOLDER_ID` sang một folder đang để "ai có link", chạy, thấy log `KHÔNG chuyển file`,
   file onboarding nằm yên trong "Google Meet", file hàng tuần vẫn chạy. Trả lại ID đúng.
6. Bật lại trigger. Đổi `OBEVAL_URL` sang obeval prod khi sẵn sàng.

## Ý nghĩa các dòng log

| Log | Ý nghĩa |
|---|---|
| `Đã chuyển: <thư mục> / <file>` | file hàng tuần đã vào `Record` (như cũ) |
| `Đã chuyển (onboarding): <thư mục> / <file>` | file onboarding đã vào folder Onboarding |
| `Onboarding: thiếu Script Properties (…) — nhánh onboarding TẮT, KHÔNG chuyển file` (error) | thiếu một trong `ONBOARDING_FOLDER_ID`, `OBEVAL_URL`, `OBEVAL_TOKEN` |
| `Onboarding: folder Onboarding không ở chế độ riêng tư (đang chia sẻ kiểu …) — nhánh onboarding TẮT …` (error) | folder không `PRIVATE` (link / domain / công khai): sửa quyền folder |
| `Onboarding: folder Onboarding đang nằm trong thùng rác …` / `không đọc được folder Onboarding (…)` (error) | folder bị xóa, `ONBOARDING_FOLDER_ID` sai, hoặc script không có quyền; nhánh tắt |
| `Onboarding: file <id> không riêng tư (link/domain) — KHÔNG chuyển` (error) | file đang chia sẻ link/domain; file nằm yên trong "Google Meet", chưa vào hàng chờ |
| `Onboarding: thư mục đích của file <id> (<id thư mục>) không riêng tư — KHÔNG chuyển` (error) | thư mục buổi họp đã có sẵn trong folder Onboarding nhưng đang chia sẻ link/domain: sửa quyền thư mục đó |
| `Onboarding: không gửi được mail cảnh báo: …` (error) | `MailApp` lỗi (hạn mức, quyền); bỏ qua, lượt sau thử lại |
| `obeval 200: <file> → {...}` | obeval đã nhận. `status` là `queued` / `in_progress` / `already_done` (file đánh dấu `transcript:sent`) hoặc `unmatched` / `ignored` / `duplicate` (không có booking khớp, hoặc booking đã có recording được chấm: `transcript:no-match` + mail `ONB_ALERT_EMAIL`) |
| `obeval <mã khác 200>: …` | lỗi phía obeval (401 sai token, 5xx...); file giữ trong hàng chờ, lượt sau gửi lại |
| `Onboarding: lỗi gọi obeval …` / `Onboarding: lỗi gửi file …` (error) | lỗi mạng hoặc Drive; giữ hàng chờ, lượt sau thử lại |
| `Onboarding: đánh dấu pending …` | `markRecentPendingOnboarding` (chạy tay sau khi sửa booking, hoặc để cứu ca kẹt `processing`) đưa lại MỌI file trong folder Onboarding tạo trong 2 ngày vào hàng chờ, kể cả file đã `sent` (obeval trả `already_done` nếu đã xong) |
| mail `nhánh onboarding đang tắt` / `N file onboarding không được chuyển` | xem lý do trong mail; tối đa 1 lần / 24 giờ. Sau khi sửa: `backfillOldRecordings` rồi `markRecentPendingOnboarding` |
| mail `… không khớp booking` | obeval `unmatched`/`ignored`: sửa booking (mã TC, giờ lệch quá 90 phút) rồi chạy tay `markRecentPendingOnboarding`. Nếu lý do là `duplicate_recording` (booking đã có recording được chấm): không chấm đè, người xem xét file nào đúng |
| mail `… bị bỏ sau 2 ngày lỗi` | file gửi lỗi liên tục quá `SEND_MAX_AGE_DAYS` ngày nên bị bỏ khỏi hàng chờ; xử lý tay |
