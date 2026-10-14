// ---- Onboarding → obeval (pdc-onboarding-eval) ----
// Tách hẳn khỏi luồng 1:1 hàng tuần: folder riêng giới hạn quyền, hàng chờ riêng, endpoint riêng.
// Script Properties: ONBOARDING_FOLDER_ID, OBEVAL_URL, OBEVAL_TOKEN, ONB_ALERT_EMAIL.
const ONBOARDING_PATTERN = /^TeenCare\s*-\s*Gia sư tâm lý 1[:_]1 Onboarding\s*-\s*TC\d+/i;
const ONB_PENDING_KEY = 'PENDING_ONBOARDING';
const OBEVAL_OK = ['queued', 'in_progress', 'already_done'];

const ONB_ALERT_AT_KEY = 'ONB_DISABLED_ALERT_AT';

let onbCfgCache_;
let onbSkipped_ = []; // file onboarding bị bỏ qua trong lượt chạy này vì file/thư mục đích không riêng tư

// Mail báo "nhánh tắt / file bị bỏ qua", tối đa 1 lần / 24 giờ (Script Property ONB_DISABLED_ALERT_AT). Không bao giờ ném lỗi.
function onbThrottledAlert_(alertTo, subject, detail) {
  try {
    if (!alertTo) return;
    const props = PropertiesService.getScriptProperties();
    const last = Number(props.getProperty(ONB_ALERT_AT_KEY)) || 0;
    if (Date.now() - last < DAY_MS) return;
    MailApp.sendEmail(alertTo, '[Onboarding recording] ' + subject,
      detail + '\n\nRecording onboarding đến trong lúc nhánh này tắt hoặc bị bỏ qua vẫn nằm trong "Google Meet"; ' +
      'chỉ được nhặt lại bằng backfillOldRecordings rồi markRecentPendingOnboarding sau khi sửa xong. ' +
      'Mail này gửi tối đa 1 lần / 24 giờ.');
    props.setProperty(ONB_ALERT_AT_KEY, String(Date.now()));
  } catch (e) {
    console.error('Onboarding: không gửi được mail cảnh báo: ' + e.message);
  }
}

function onbDisable_(alertTo, reason) {
  console.error('Onboarding: ' + reason + ' — nhánh onboarding TẮT, KHÔNG chuyển file');
  onbThrottledAlert_(alertTo, 'nhánh onboarding đang tắt', 'Lý do: ' + reason + '.');
  return null;
}

// Cảnh báo gửi mail nếu có ONB_ALERT_EMAIL, không thì ghi console.error để vẫn lên nhật ký Executions
function onbReport_(alertTo, subject, body) {
  if (alertTo) MailApp.sendEmail(alertTo, subject, body);
  else console.error(subject + '\n' + body);
}

// null = nhánh onboarding tắt (thiếu cấu hình, folder không đọc được / đã vào thùng rác / không riêng tư) — luồng hàng tuần chạy bình thường
function onboardingConfig_() {
  if (onbCfgCache_ !== undefined) return onbCfgCache_;
  onbCfgCache_ = null;
  const p = PropertiesService.getScriptProperties();
  const cfg = {folderId: p.getProperty('ONBOARDING_FOLDER_ID'), url: p.getProperty('OBEVAL_URL'),
               token: p.getProperty('OBEVAL_TOKEN'), alert: p.getProperty('ONB_ALERT_EMAIL')};
  if (!cfg.folderId || !cfg.url || !cfg.token) {
    return onbDisable_(cfg.alert, 'thiếu Script Properties (ONBOARDING_FOLDER_ID / OBEVAL_URL / OBEVAL_TOKEN)');
  }
  let folder;
  let access;
  let trashed;
  try {
    folder = DriveApp.getFolderById(cfg.folderId);
    trashed = folder.isTrashed();
    access = folder.getSharingAccess();
  } catch (e) {
    return onbDisable_(cfg.alert, 'không đọc được folder Onboarding (' + e.message + ')');
  }
  if (trashed) return onbDisable_(cfg.alert, 'folder Onboarding đang nằm trong thùng rác');
  // Danh sách cho phép: video trẻ em chỉ được vào folder PRIVATE (chỉ người được chia sẻ đích danh), mọi kiểu link/domain đều bị chặn
  if (access !== DriveApp.Access.PRIVATE) {
    return onbDisable_(cfg.alert, 'folder Onboarding không ở chế độ riêng tư (đang chia sẻ kiểu ' + access + ': link / domain / công khai)');
  }
  cfg.folder = folder;
  onbCfgCache_ = cfg;
  return cfg;
}

function isOnboardingMeeting(name) {
  return ONBOARDING_PATTERN.test(name.normalize('NFC')) && onboardingConfig_() !== null;
}

// Folder đích cho file onboarding, hoặc null nếu KHÔNG được chuyển: file và thư mục đích đều phải PRIVATE.
// Gọi TRƯỚC khi đánh dấu pending: file bị chặn không vào hàng chờ, không bị đổi description.
function onboardingDestination_(video, meetingName) {
  const cfg = onboardingConfig_();
  if (!cfg) return null;
  if (video.getSharingAccess() !== DriveApp.Access.PRIVATE) {
    console.error('Onboarding: file ' + video.getId() + ' không riêng tư (link/domain) — KHÔNG chuyển');
    onbSkipped_.push(video.getId());
    return null;
  }
  const dest = getOrCreateFolder(cfg.folder, meetingName);
  if (dest.getSharingAccess() !== DriveApp.Access.PRIVATE) {
    console.error('Onboarding: thư mục đích của file ' + video.getId() + ' (' + dest.getId() + ') không riêng tư — KHÔNG chuyển');
    onbSkipped_.push(video.getId());
    return null;
  }
  return dest;
}

// Gửi obeval các file trong hàng chờ đã nằm trong folder Onboarding; lỗi thì giữ lại để lượt sau gửi tiếp
function sendPendingOnboarding() {
  const cfg = onboardingConfig_();
  if (!cfg) return;
  const pending = getPending(ONB_PENDING_KEY);
  const noMatch = [];
  const expired = [];
  for (const id of Object.keys(pending)) {
    const isExpired = Date.now() - pending[id] > SEND_MAX_AGE_DAYS * DAY_MS;
    let label = 'https://drive.google.com/file/d/' + id + '/view';
    let reason = 'chưa chuyển được sang folder Onboarding';
    try {
      const video = DriveApp.getFileById(id);
      label = video.getName() + '\n  ' + video.getUrl();
      const meeting = firstParent(video);
      const parent = meeting ? firstParent(meeting) : null;
      if (parent && parent.getId() === cfg.folderId) {
        const result = notifyObeval_(video, cfg);
        if (result.status === 'sent') {
          video.setDescription(MARK_SENT);
          delete pending[id];
          continue;
        }
        if (result.status === 'no-match') {
          video.setDescription(MARK_NO_MATCH);
          noMatch.push(label + '\n  Lý do: ' + result.detail);
          delete pending[id];
          continue;
        }
        reason = result.detail;
      }
    } catch (e) {
      reason = e.message;
      console.error('Onboarding: lỗi gửi file ' + id + ': ' + e.message);
    }
    if (isExpired) {
      expired.push(label + '\n  Lý do: ' + reason);
      delete pending[id];
    }
  }
  setPending(pending, ONB_PENDING_KEY);
  if (onbSkipped_.length) {
    onbThrottledAlert_(cfg.alert, onbSkipped_.length + ' file onboarding không được chuyển',
      onbSkipped_.length + ' file onboarding KHÔNG được chuyển vì file hoặc thư mục đích đang chia sẻ bằng link/domain ' +
      '(id file nằm trong nhật ký Executions)');
  }
  if (noMatch.length) {
    onbReport_(cfg.alert, '[Onboarding recording] ' + noMatch.length + ' file không khớp booking',
      'obeval không ghép được với booking onboarding nào (no_booking: sai mã TC / lệch giờ > 90 phút; ' +
      'unparsable_name: tên file không đọc được; duplicate_recording: booking đã có recording được chấm, file này không chấm đè). ' +
      'Với no_booking / unparsable_name: sửa booking xong chạy markRecentPendingOnboarding. ' +
      'Với duplicate_recording: người quyết định file nào đúng (file này nằm trong bảng onboarding_recording_unmatched).\n\n' +
      noMatch.join('\n\n'));
  }
  if (expired.length) {
    onbReport_(cfg.alert, '[Onboarding recording] ' + expired.length + ' file bị bỏ sau ' + SEND_MAX_AGE_DAYS + ' ngày lỗi',
      'Gửi obeval không thành công trong ' + SEND_MAX_AGE_DAYS + ' ngày.\n\n' + expired.join('\n\n'));
  }
}

// 'sent' = obeval đã nhận (đang xử lý / đã xong) · 'no-match' = không có booking khớp · 'error' = lượt sau gửi lại
function notifyObeval_(video, cfg) {
  const payload = {id: video.getId(), name: video.getName(), webViewLink: video.getUrl(),
                   createdTime: video.getDateCreated().toISOString()};
  try {
    const res = UrlFetchApp.fetch(cfg.url.replace(/\/$/, '') + '/v1/recordings', {
      method: 'post', contentType: 'application/json', muteHttpExceptions: true,
      headers: {'X-Obeval-Token': cfg.token}, payload: JSON.stringify(payload),
    });
    const code = res.getResponseCode();
    const text = res.getContentText();
    console.log('obeval ' + code + ': ' + video.getName() + ' → ' + text);
    if (code !== 200) return {status: 'error', detail: 'HTTP ' + code + ': ' + text.slice(0, 200)};
    const body = JSON.parse(text);
    if (OBEVAL_OK.indexOf(body.status) >= 0) return {status: 'sent'};
    if (body.status === 'unmatched' || body.status === 'ignored') return {status: 'no-match', detail: body.reason || body.status};
    if (body.status === 'duplicate') {
      return {status: 'no-match', detail: 'duplicate_recording: booking này đã có recording được chấm, file này KHÔNG được chấm đè — người xem xét'};
    }
    return {status: 'error', detail: 'obeval trả: ' + text.slice(0, 200)};
  } catch (e) {
    console.error('Onboarding: lỗi gọi obeval ' + video.getName() + ': ' + e.message);
    return {status: 'error', detail: e.message};
  }
}

// Chạy tay sau khi sửa booking (hoặc để cứu ca kẹt): đưa MỌI mp4 trong folder Onboarding tạo trong 2 ngày vào hàng chờ, kể cả file đã sent
function markRecentPendingOnboarding() {
  const cfg = onboardingConfig_();
  if (!cfg) return;
  const cutoff = Date.now() - SEND_MAX_AGE_DAYS * DAY_MS;
  const files = searchMp4Since(cutoff);
  while (files.hasNext()) {
    const video = files.next();
    const meeting = firstParent(video);
    const parent = meeting ? firstParent(meeting) : null;
    if (!parent || parent.getId() !== cfg.folderId) continue;
    if (video.getDateCreated().getTime() > cutoff) {
      // KHÔNG bỏ qua file đã MARK_SENT: register của obeval idempotent (already_done không tốn gì), còn file kẹt
      // ở 'processing' chỉ được nhặt lại nhờ lần gửi này.
      video.setDescription(MARK_PENDING);
      addPending(video.getId(), ONB_PENDING_KEY);
      console.log('Onboarding: đánh dấu pending ' + video.getName());
    }
  }
}
