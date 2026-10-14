// Bản lưu trong repo pdc-onboarding-eval của Code.gs đang chạy + nhánh onboarding (xem README.md).
// Ba hằng số bên dưới (PUBLIC_FOLDER_ID, WEBHOOK_URL, ALERT_EMAIL) là PLACEHOLDER: giá trị thật chỉ nằm trong script đang chạy,
// KHÔNG dán lại vào repo. Khi áp dụng lên script thật, chỉ sửa các hàm được liệt kê trong README, giữ nguyên ba hằng số thật.
const PUBLIC_FOLDER_ID = '<PUBLIC_FOLDER_ID>';
const MEET_ROOT_NAME = 'Google Meet';
const MEETING_PATTERN = /^TeenCare\s*-\s*Gia sư Mentor 1:1 hàng tuần\s*-\s*TC\d+/i;
const WEBHOOK_URL = '<SESSION_ON_TRIGGER_DRIVE_WEBHOOK_URL>';
const HOUR_MS = 60 * 60 * 1000;
const DAY_MS = 24 * HOUR_MS;
const LOOKBACK_HOURS = 6;              // mỗi lần chạy chỉ quét mp4 thay đổi trong 6 giờ gần nhất
const SEND_MAX_AGE_DAYS = 2;           // chỉ gửi worker recording tạo trong 2 ngày
const TIME_BUDGET_MS = 10 * 60 * 1000; // dừng quét sau 10 phút, chừa thời gian gửi webhook
const MARK_PENDING = 'transcript:pending';
const MARK_SENT = 'transcript:sent';
const PENDING_KEY = 'PENDING_RECORDINGS';
const BACKFILL_ONLY_1_1 = true;        // moveFromOldPublicFolders: false = chuyển cả buổi không phải 1:1
const MARK_NO_MATCH = 'transcript:no-match';
const ALERT_EMAIL = '<ALERT_EMAIL>';

function syncMeetRecordings() {
  const lock = LockService.getScriptLock();
  if (!lock.tryLock(1000)) {
    console.warn('Đang có lần chạy khác, bỏ qua');
    return;
  }
  try {
    scanAndMove(Date.now() - LOOKBACK_HOURS * HOUR_MS);
    sendPending();
    sendPendingOnboarding();
  } finally {
    lock.releaseLock();
  }
}

// Chạy tay: chuyển recording cũ (180 ngày) còn nằm trong thư mục Meet đang dùng
function backfillOldRecordings() {
  scanAndMove(Date.now() - 180 * DAY_MS);
  sendPending();
  sendPendingOnboarding();
}

// Chuyển mp4 của buổi 1:1 trong thư mục "Google Meet" đang dùng sang Record.
// Lỗi ở một file chỉ bỏ qua file đó; lần chạy sau quét lại và thử tiếp.
function scanAndMove(sinceMs) {
  const started = Date.now();
  const publicRoot = DriveApp.getFolderById(PUBLIC_FOLDER_ID);
  const activeRoots = getActiveMeetRootIds();
  const sendCutoff = Date.now() - SEND_MAX_AGE_DAYS * DAY_MS;
  const meetingNames = new Map(); // id thư mục buổi họp -> {name, kind}; kind = 'weekly' | 'onboarding' | '' (bỏ qua)
  const files = searchMp4Since(sinceMs);

  while (files.hasNext()) {
    if (Date.now() - started > TIME_BUDGET_MS) {
      console.warn('Sắp hết giờ, lần chạy sau quét tiếp');
      return;
    }
    const video = files.next();
    try {
      const meeting = firstParent(video);
      if (!meeting) continue;
      const meetingId = meeting.getId();
      if (!meetingNames.has(meetingId)) {
        const root = firstParent(meeting);
        const name = meeting.getName();
        const active = root !== null && activeRoots.has(root.getId());
        const kind = !active ? ''
          : MEETING_PATTERN.test(name.normalize('NFC')) ? 'weekly'
          : isOnboardingMeeting(name) ? 'onboarding' : '';
        meetingNames.set(meetingId, {name: name, kind: kind});
      }
      const m = meetingNames.get(meetingId);
      if (!m.kind) continue;
      const onboarding = m.kind === 'onboarding';
      let onbDest = null;
      if (onboarding) {
        onbDest = onboardingDestination_(video, m.name);
        if (!onbDest) continue;
      }

      // Đánh dấu TRƯỚC khi chuyển: bị ngắt giữa chừng thì file vẫn còn trong danh sách gửi
      if (video.getDateCreated().getTime() > sendCutoff) {
        video.setDescription(MARK_PENDING);
        addPending(video.getId(), onboarding ? ONB_PENDING_KEY : PENDING_KEY);
      }
      video.moveTo(onboarding ? onbDest : getOrCreateFolder(publicRoot, m.name));
      console.log('Đã chuyển' + (onboarding ? ' (onboarding)' : '') + ': ' + m.name + ' / ' + video.getName());
    } catch (e) {
      console.error('Lỗi với file ' + video.getId() + ': ' + e.message + ' (lần chạy sau thử lại)');
    }
  }
}

// Gửi webhook cho các file trong danh sách pending đã nằm trong Record; lỗi thì giữ lại để lần sau gửi tiếp
function sendPending() {
  const pending = getPending();
  const noMatch = [];
  const expired = [];

  for (const id of Object.keys(pending)) {
    const isExpired = Date.now() - pending[id] > SEND_MAX_AGE_DAYS * DAY_MS;
    let label = 'https://drive.google.com/file/d/' + id + '/view';
    let reason = 'chưa chuyển được sang Record';
    try {
      const video = DriveApp.getFileById(id);
      label = video.getName() + '\n  ' + video.getUrl();
      const meeting = firstParent(video);
      const parent = meeting ? firstParent(meeting) : null;
      if (parent && parent.getId() === PUBLIC_FOLDER_ID) {
        const result = notifyWorker(video);
        if (result.status === 'sent') {
          video.setDescription(MARK_SENT);
          delete pending[id];
          continue;
        }
        if (result.status === 'no-match') {
          video.setDescription(MARK_NO_MATCH);
          noMatch.push(label);
          delete pending[id];
          continue;
        }
        reason = result.detail;
      }
    } catch (e) {
      reason = e.message;
      console.error('Lỗi gửi file ' + id + ': ' + e.message);
    }
    if (isExpired) {
      expired.push(label + '\n  Lý do: ' + reason);
      delete pending[id];
    }
  }
  setPending(pending);

  sendAlert(noMatch.length + ' recording không khớp buổi LMS nào',
    'Webhook trả 200 nhưng "ids":[] (không lỗi). Kiểm tra mã TC và giờ trong tên file so với lịch trên LMS.\n' +
    'Sửa xong thì chạy markRecentPending để gửi lại.', noMatch);
  sendAlert(expired.length + ' recording bị bỏ khỏi hàng chờ sau ' + SEND_MAX_AGE_DAYS + ' ngày lỗi',
    'Các file dưới đây gửi webhook không thành công trong ' + SEND_MAX_AGE_DAYS + ' ngày nên đã bị bỏ khỏi hàng chờ.', expired);
}

// Chạy tay khi cần gửi lại: đưa mp4 trong Record tạo trong 2 ngày mà chưa gửi vào danh sách pending
function markRecentPending() {
  const cutoff = Date.now() - SEND_MAX_AGE_DAYS * DAY_MS;
  const files = searchMp4Since(cutoff);
  while (files.hasNext()) {
    const video = files.next();
    const meeting = firstParent(video);
    const parent = meeting ? firstParent(meeting) : null;
    if (!parent || parent.getId() !== PUBLIC_FOLDER_ID) continue;
    if (video.getDateCreated().getTime() > cutoff && video.getDescription() !== MARK_SENT) {
      video.setDescription(MARK_PENDING);
      addPending(video.getId());
      console.log('Đánh dấu pending: ' + video.getName());
    }
  }
}

// Chạy tay: chuyển video từ các thư mục "Google Meet" cũ đã public sang Record. KHÔNG gọi webhook.
function moveFromOldPublicFolders() {
  const started = Date.now();
  const publicRoot = DriveApp.getFolderById(PUBLIC_FOLDER_ID);
  let moved = 0;
  const roots = DriveApp.getRootFolder().getFoldersByName(MEET_ROOT_NAME);

  while (roots.hasNext()) {
    const root = roots.next();
    if (root.getSharingAccess() !== DriveApp.Access.ANYONE_WITH_LINK) continue;

    const meetings = root.getFolders();
    while (meetings.hasNext()) {
      if (Date.now() - started > TIME_BUDGET_MS) {
        console.warn('Sắp hết giờ, lần này đã chuyển ' + moved + ' video. Bấm Chạy lại để làm tiếp.');
        return;
      }
      const meeting = meetings.next();
      const name = meeting.getName();
      if (BACKFILL_ONLY_1_1 && !MEETING_PATTERN.test(name.normalize('NFC'))) continue;

      const videos = meeting.getFilesByType('video/mp4');
      while (videos.hasNext()) {
        const video = videos.next();
        video.moveTo(getOrCreateFolder(publicRoot, name));
        moved++;
        console.log('Đã chuyển: ' + name + ' / ' + video.getName());
      }
    }
  }
  console.log('Xong, lần này chuyển ' + moved + ' video.');
}

function getActiveMeetRootIds() {
  const ids = new Set();
  const roots = DriveApp.getRootFolder().getFoldersByName(MEET_ROOT_NAME);
  while (roots.hasNext()) {
    const root = roots.next();
    if (root.getSharingAccess() !== DriveApp.Access.ANYONE_WITH_LINK) ids.add(root.getId());
  }
  return ids;
}

function searchMp4Since(ms) {
  const since = new Date(ms).toISOString().replace(/\.\d+Z$/, 'Z');
  return DriveApp.searchFiles(
    "mimeType = 'video/mp4' and trashed = false and 'me' in owners and modifiedDate > '" + since + "'");
}

function searchRecentMp4(days) {
  return searchMp4Since(Date.now() - days * DAY_MS);
}

function firstParent(item) {
  const it = item.getParents();
  return it.hasNext() ? it.next() : null;
}

function getPending(key) {
  return JSON.parse(PropertiesService.getScriptProperties().getProperty(key || PENDING_KEY) || '{}');
}

function setPending(pending, key) {
  PropertiesService.getScriptProperties().setProperty(key || PENDING_KEY, JSON.stringify(pending));
}

function addPending(id, key) {
  const pending = getPending(key);
  if (!(id in pending)) {
    pending[id] = Date.now();
    setPending(pending, key);
  }
}

// Gọi webhook. status: 'sent' = khớp buổi LMS · 'no-match' = 200 nhưng ids rỗng, không lỗi · 'error' = lần sau gửi lại
function notifyWorker(video) {
  const payload = [{
    id: video.getId(),
    name: video.getName(),
    webViewLink: video.getUrl(),
    createdTime: video.getDateCreated().toISOString(),
  }];
  try {
    const res = UrlFetchApp.fetch(WEBHOOK_URL, {
      method: 'post',
      contentType: 'application/json',
      payload: JSON.stringify(payload),
      muteHttpExceptions: true,
    });
    const code = res.getResponseCode();
    const text = res.getContentText();
    console.log('Worker ' + code + ': ' + video.getName() + ' → ' + text);
    if (code !== 200) return { status: 'error', detail: 'HTTP ' + code + ': ' + text.slice(0, 200) };
    const body = JSON.parse(text);
    if ((body.ids || []).length > 0) return { status: 'sent' };
    if ((body.errors || []).length > 0) return { status: 'error', detail: 'webhook báo lỗi: ' + body.errors.join('; ').slice(0, 200) };
    return { status: 'no-match' };
  } catch (e) {
    console.error('Lỗi gọi worker ' + video.getName() + ': ' + e.message);
    return { status: 'error', detail: e.message };
  }
}

function sendAlert(subject, intro, items) {
  if (items.length === 0) return;
  MailApp.sendEmail(ALERT_EMAIL, '[Meet recording] ' + subject, intro + '\n\n' + items.join('\n\n'));
}

// Chạy tay MỘT LẦN sau khi dán code: cấp quyền gửi mail và kiểm tra mail tới được
function testAlert() {
  sendAlert('Thử cảnh báo', 'Mail thử từ Apps Script đồng bộ recording.', ['Đọc được dòng này là cảnh báo đã hoạt động.']);
}

function getOrCreateFolder(parent, name) {
  const it = parent.getFoldersByName(name);
  return it.hasNext() ? it.next() : parent.createFolder(name);
}

function createTrigger() {
  ScriptApp.newTrigger('syncMeetRecordings').timeBased().everyMinutes(15).create();
}
