// Chạy: node tests/apps_script/test_apps_script.js
// Nạp tools/apps_script/Code.gs + onboarding.gs vào MỘT vm context (như project Apps Script thật),
// dùng bản giả của DriveApp / PropertiesService / UrlFetchApp / MailApp... — không có mạng, không có dịch vụ Google.
'use strict';
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const assert = require('node:assert');

const ROOT = path.join(__dirname, '..', '..', 'tools', 'apps_script');
const CODE = fs.readFileSync(path.join(ROOT, 'Code.gs'), 'utf8');
const ONB = fs.readFileSync(path.join(ROOT, 'onboarding.gs'), 'utf8');

// Giá trị giả — khớp với placeholder trong Code.gs, không phải ID/URL/email thật
const PUBLIC_ID = '<PUBLIC_FOLDER_ID>';
const WEBHOOK = '<SESSION_ON_TRIGGER_DRIVE_WEBHOOK_URL>';
const OBEVAL = 'https://obeval.example';
const ONB_ID = 'fake-onboarding-folder-id';
const FAKE_TOKEN = 'fake-token-not-real';
const ONB_MAIL = 'onb-alerts@example.invalid';
const WEEKLY_MAIL = '<ALERT_EMAIL>';

const HOUR = 3600 * 1000;
const DAY = 24 * HOUR;

const WEEKLY_NAME = 'TeenCare - Gia sư Mentor 1:1 hàng tuần - TC1234 - 2026/10/14 19:00 GMT+07:00';
const ONB_NAME = 'TeenCare - Gia sư tâm lý 1:1 Onboarding - TC5678 - 2026/10/14 20:00 GMT+07:00';
const OTHER_NAME = 'Họp nội bộ không liên quan - 2026/10/14 10:00 GMT+07:00';

// ---------- Drive giả ----------
function makeIter(arr) {
  let i = 0;
  return { hasNext: () => i < arr.length, next: () => arr[i++] };
}

class Node {
  constructor(drive, id, name, isFolder) {
    this.drive = drive;
    this.id = id;
    this.name = name;
    this.isFolder = isFolder;
    this.parent = null;
    this.access = 'PRIVATE';
    this.description = '';
    this.created = new Date();
    this.modified = new Date();
    this.mime = isFolder ? 'application/vnd.google-apps.folder' : 'video/mp4';
    this.owner = 'me';
    this.trashed = false;
  }
  getId() { return this.id; }
  getName() { return this.name; }
  getUrl() { return 'https://drive.example/' + this.id; }
  getParents() { return makeIter(this.parent ? [this.parent] : []); }
  getSharingAccess() { return this.access; }
  isTrashed() { return this.trashed; }
  setDescription(d) { this.description = d; this.modified = new Date(); return this; } // Drive thật cập nhật modifiedDate
  getDescription() { return this.description; }
  getDateCreated() { return this.created; }
  children() { return this.drive.nodes.filter((n) => n.parent === this); }
  getFolders() { return makeIter(this.children().filter((n) => n.isFolder)); }
  getFiles() { return makeIter(this.children().filter((n) => !n.isFolder)); }
  getFilesByType(m) { return makeIter(this.children().filter((n) => !n.isFolder && n.mime === m)); }
  getFoldersByName(name) { return makeIter(this.children().filter((n) => n.isFolder && n.name === name)); }
  createFolder(name) { return this.drive.addFolder(this, name); }
  moveTo(dest) {
    this.parent = dest;
    this.modified = new Date();
    this.drive.moves.push({ file: this.id, to: dest.id });
    return this;
  }
}

class Drive {
  constructor() {
    this.nodes = [];
    this.moves = [];
    this.seq = 0;
    this.root = this.addFolder(null, 'My Drive', 'root-id');
    this.meetRoot = this.addFolder(this.root, 'Google Meet', 'meet-root-id');
    this.record = this.addFolder(this.root, 'Record', PUBLIC_ID);
    this.onboarding = this.addFolder(this.root, 'Onboarding recordings', ONB_ID);
  }
  addFolder(parent, name, id) {
    const n = new Node(this, id || 'folder-' + ++this.seq, name, true);
    n.parent = parent;
    this.nodes.push(n);
    return n;
  }
  // Tạo video do 'me' sở hữu trong một thư mục buổi họp con của "Google Meet"
  addMeetVideo(meetingName, opts = {}) {
    const meeting = this.addFolder(opts.meetingParent || this.meetRoot, meetingName);
    return this.addVideoIn(meeting, opts);
  }
  addVideoIn(meeting, opts = {}) {
    const v = new Node(this, opts.id || 'video-' + ++this.seq, opts.name || 'rec-' + (this.seq) + '.mp4', false);
    v.parent = meeting;
    if (opts.modifiedAgoMs !== undefined) v.modified = new Date(Date.now() - opts.modifiedAgoMs);
    if (opts.createdAgoMs !== undefined) v.created = new Date(Date.now() - opts.createdAgoMs);
    this.nodes.push(v);
    return v;
  }
  byId(id) {
    const n = this.nodes.find((x) => x.id === id);
    if (!n) throw new Error('Drive: không có ' + id);
    return n;
  }
  // Chỉ hiểu đúng mẫu truy vấn của searchMp4Since
  searchFiles(q) {
    const m = /modifiedDate > '([^']+)'/.exec(q);
    assert.ok(m, 'truy vấn không có modifiedDate');
    assert.ok(/mimeType = 'video\/mp4'/.test(q) && /'me' in owners/.test(q) && /trashed = false/.test(q), 'truy vấn lệch: ' + q);
    const since = new Date(m[1]).getTime();
    return makeIter(this.nodes.filter((n) => !n.isFolder && n.mime === 'video/mp4' && n.owner === 'me' &&
      !n.trashed && n.modified.getTime() > since));
  }
}

// ---------- Môi trường ----------
function makeEnv({ props = {}, onbProps = true, onbAccess = 'PRIVATE', fetchHandler, mailThrows = false } = {}) {
  const drive = new Drive();
  drive.onboarding.access = onbAccess;
  const store = new Map();
  if (onbProps) {
    store.set('ONBOARDING_FOLDER_ID', ONB_ID);
    store.set('OBEVAL_URL', OBEVAL);
    store.set('OBEVAL_TOKEN', FAKE_TOKEN);
    store.set('ONB_ALERT_EMAIL', ONB_MAIL);
  }
  for (const [k, v] of Object.entries(props)) {
    if (v === null) store.delete(k); else store.set(k, v);
  }
  const fetches = [];
  const mails = [];
  const logs = { log: [], warn: [], error: [] };
  const resp = (code, text) => ({ getResponseCode: () => code, getContentText: () => text });

  const sandbox = {
    DriveApp: {
      Access: { ANYONE: 'ANYONE', ANYONE_WITH_LINK: 'ANYONE_WITH_LINK', DOMAIN: 'DOMAIN', DOMAIN_WITH_LINK: 'DOMAIN_WITH_LINK', PRIVATE: 'PRIVATE' },
      getFolderById: (id) => drive.byId(id),
      getFileById: (id) => drive.byId(id),
      getRootFolder: () => drive.root,
      searchFiles: (q) => drive.searchFiles(q),
    },
    PropertiesService: {
      getScriptProperties: () => ({
        getProperty: (k) => (store.has(k) ? store.get(k) : null),
        setProperty: (k, v) => { store.set(k, String(v)); },
      }),
    },
    LockService: { getScriptLock: () => ({ tryLock: () => true, releaseLock: () => {} }) },
    UrlFetchApp: {
      fetch: (url, options) => {
        // sao chép sang realm của test để assert so sánh được
        fetches.push({ url, options: JSON.parse(JSON.stringify(options)) });
        return fetchHandler(url, options, resp);
      },
    },
    MailApp: { sendEmail: (to, subject, body) => { if (mailThrows) throw new Error('mail quota'); mails.push({ to, subject, body }); } },
    ScriptApp: { newTrigger: () => { throw new Error('không dùng trong test'); } },
    console: {
      log: (...a) => logs.log.push(a.join(' ')),
      warn: (...a) => logs.warn.push(a.join(' ')),
      error: (...a) => logs.error.push(a.join(' ')),
    },
  };
  // Mỗi lần chạy là một vm context MỚI (như mỗi lượt thực thi Apps Script): biến cấp module như onbCfgCache_ không sống qua các lượt
  const freshCtx = () => {
    const c = vm.createContext(Object.assign({}, sandbox)); // sandbox mới mỗi lần, các bản giả bên trong dùng chung
    vm.runInContext(CODE, c, { filename: 'Code.gs' });
    vm.runInContext(ONB, c, { filename: 'onboarding.gs' });
    return c;
  };
  const run = (fn) => vm.runInContext(fn + '()', freshCtx());
  const evalIn = (code) => vm.runInContext(code, freshCtx());
  const prop = (k) => (store.has(k) ? store.get(k) : null);
  const pending = (k) => JSON.parse(store.get(k) || '{}');
  return { drive, store, fetches, mails, logs, run, evalIn, prop, pending, resp };
}

// Handler: webhook cũ trả theo `weekly`, obeval trả theo `obeval`
function handlers({ weekly, obeval }) {
  return (url, options, resp) => {
    if (url === WEBHOOK) return weekly(url, options, resp);
    if (url.startsWith(OBEVAL)) return obeval(url, options, resp);
    throw new Error('URL lạ: ' + url);
  };
}
const weeklyOk = (u, o, resp) => resp(200, JSON.stringify({ ids: ['x'], errors: [] }));
const weeklyDown = (u, o, resp) => resp(500, 'boom');
const obevalStatus = (s, extra = {}) => (u, o, resp) => resp(200, JSON.stringify(Object.assign({ status: s }, extra)));
const obevalNever = () => { throw new Error('không được gọi obeval'); };
const webhookNever = () => { throw new Error('không được gọi webhook hàng tuần'); };

function pathOf(node) {
  const parts = [];
  for (let n = node; n; n = n.parent) parts.unshift(n.name);
  return parts.join(' / ');
}

// ---------- Khung chạy test ----------
let passed = 0;
const failures = [];
function test(name, fn) {
  try {
    fn();
    passed++;
    console.log('ok   - ' + name);
  } catch (e) {
    failures.push(name);
    console.log('FAIL - ' + name + '\n       ' + (e && e.stack || e).split('\n').join('\n       '));
  }
}

// ---------- (a) hàng tuần: hành vi cũ ----------
test('(a) weekly: chuyển vào Record, pending ở PENDING_RECORDINGS, gửi webhook mảng gốc, đánh dấu sent', () => {
  let weeklyUp = false;
  const env = makeEnv({
    fetchHandler: handlers({ weekly: (u, o, r) => (weeklyUp ? weeklyOk(u, o, r) : weeklyDown(u, o, r)), obeval: obevalNever }),
  });
  const v = env.drive.addMeetVideo(WEEKLY_NAME, { name: 'weekly.mp4', id: 'vid-weekly' });

  env.run('syncMeetRecordings');
  assert.strictEqual(pathOf(v), 'My Drive / Record / ' + WEEKLY_NAME + ' / weekly.mp4');
  assert.deepStrictEqual(Object.keys(env.pending('PENDING_RECORDINGS')), ['vid-weekly']);
  assert.deepStrictEqual(env.pending('PENDING_ONBOARDING'), {}, 'weekly không được đưa gì vào hàng chờ onboarding');
  assert.strictEqual(v.getDescription(), 'transcript:pending', 'webhook lỗi → vẫn pending');
  assert.ok(env.logs.log.includes('Đã chuyển: ' + WEEKLY_NAME + ' / weekly.mp4'));

  weeklyUp = true;
  env.run('syncMeetRecordings');
  assert.strictEqual(v.getDescription(), 'transcript:sent');
  assert.deepStrictEqual(env.pending('PENDING_RECORDINGS'), {});
  const calls = env.fetches.filter((f) => f.url === WEBHOOK);
  assert.strictEqual(calls.length, 2);
  const last = calls[1];
  assert.strictEqual(last.options.method, 'post');
  assert.strictEqual(last.options.contentType, 'application/json');
  assert.strictEqual(last.options.muteHttpExceptions, true);
  assert.strictEqual(last.options.headers, undefined, 'webhook cũ không có header');
  const payload = JSON.parse(last.options.payload);
  assert.ok(Array.isArray(payload) && payload.length === 1);
  assert.deepStrictEqual(Object.keys(payload[0]).sort(), ['createdTime', 'id', 'name', 'webViewLink']);
  assert.strictEqual(payload[0].id, 'vid-weekly');
  assert.strictEqual(payload[0].name, 'weekly.mp4');
  assert.strictEqual(payload[0].webViewLink, 'https://drive.example/vid-weekly');

  // chạy lần nữa: không gửi lại gì
  const before = env.fetches.length;
  env.run('syncMeetRecordings');
  assert.strictEqual(env.fetches.length, before);
});

test('(a2) weekly: webhook 200 nhưng ids rỗng → no-match, mail về ALERT_EMAIL cũ (không phải ONB_ALERT_EMAIL)', () => {
  const env = makeEnv({
    fetchHandler: handlers({ weekly: (u, o, r) => r(200, JSON.stringify({ ids: [], errors: [] })), obeval: obevalNever }),
  });
  const v = env.drive.addMeetVideo(WEEKLY_NAME, { id: 'vid-w2' });
  env.run('syncMeetRecordings');
  assert.strictEqual(v.getDescription(), 'transcript:no-match');
  assert.strictEqual(env.mails.length, 1);
  assert.strictEqual(env.mails[0].to, WEEKLY_MAIL);
  assert.ok(env.mails[0].subject.startsWith('[Meet recording]'));
});

// ---------- (b) onboarding đường chính ----------
test('(b) onboarding: chuyển vào folder Onboarding, POST obeval 1 object + header token, queued → sent, pending sạch', () => {
  const env = makeEnv({ fetchHandler: handlers({ weekly: webhookNever, obeval: obevalStatus('queued') }) });
  const v = env.drive.addMeetVideo(ONB_NAME, { name: 'onb.mp4', id: 'vid-onb' });

  env.run('syncMeetRecordings');
  assert.strictEqual(pathOf(v), 'My Drive / Onboarding recordings / ' + ONB_NAME + ' / onb.mp4');
  assert.strictEqual(env.drive.record.children().length, 0, 'Record không được nhận gì');
  assert.deepStrictEqual(env.pending('PENDING_RECORDINGS'), {}, 'onboarding không được đưa gì vào hàng chờ hàng tuần');
  assert.deepStrictEqual(env.pending('PENDING_ONBOARDING'), {});
  assert.strictEqual(v.getDescription(), 'transcript:sent');
  assert.ok(env.logs.log.includes('Đã chuyển (onboarding): ' + ONB_NAME + ' / onb.mp4'));

  assert.strictEqual(env.fetches.length, 1);
  const f = env.fetches[0];
  assert.strictEqual(f.url, OBEVAL + '/v1/recordings');
  assert.strictEqual(f.options.method, 'post');
  assert.strictEqual(f.options.contentType, 'application/json');
  assert.deepStrictEqual(f.options.headers, { 'X-Obeval-Token': FAKE_TOKEN });
  const payload = JSON.parse(f.options.payload);
  assert.ok(!Array.isArray(payload), 'obeval nhận một object, không phải mảng');
  assert.deepStrictEqual(Object.keys(payload).sort(), ['createdTime', 'id', 'name', 'webViewLink']);
  assert.strictEqual(payload.id, 'vid-onb');
  assert.strictEqual(payload.name, 'onb.mp4');
  assert.strictEqual(payload.webViewLink, 'https://drive.example/vid-onb');
  assert.ok(!Number.isNaN(Date.parse(payload.createdTime)));
  assert.strictEqual(env.mails.length, 0);

  // lần sau không gửi lại
  env.run('syncMeetRecordings');
  assert.strictEqual(env.fetches.length, 1);
});

test('(b2) onboarding: in_progress / already_done cũng tính là đã nhận; URL có "/" cuối vẫn đúng', () => {
  for (const s of ['in_progress', 'already_done']) {
    const env = makeEnv({
      props: { OBEVAL_URL: OBEVAL + '/' },
      fetchHandler: handlers({ weekly: webhookNever, obeval: obevalStatus(s) }),
    });
    const v = env.drive.addMeetVideo(ONB_NAME, { id: 'vid-' + s });
    env.run('syncMeetRecordings');
    assert.strictEqual(v.getDescription(), 'transcript:sent', s);
    assert.strictEqual(env.fetches[0].url, OBEVAL + '/v1/recordings');
  }
});

// ---------- (c) obeval lỗi ----------
test('(c) obeval 500: giữ trong PENDING_ONBOARDING, không đánh dấu sent, lượt sau gửi lại được', () => {
  let ok = false;
  const env = makeEnv({
    fetchHandler: handlers({
      weekly: webhookNever,
      obeval: (u, o, r) => (ok ? r(200, '{"status":"queued"}') : r(500, 'internal error')),
    }),
  });
  const v = env.drive.addMeetVideo(ONB_NAME, { id: 'vid-c' });
  env.run('syncMeetRecordings');
  assert.strictEqual(v.getDescription(), 'transcript:pending');
  assert.deepStrictEqual(Object.keys(env.pending('PENDING_ONBOARDING')), ['vid-c']);
  assert.deepStrictEqual(env.pending('PENDING_RECORDINGS'), {}, 'onboarding không được đưa gì vào hàng chờ hàng tuần');
  assert.strictEqual(env.mails.length, 0, 'chưa hết hạn thì chưa báo');
  assert.ok(env.logs.log.some((l) => l.startsWith('obeval 500:')));

  ok = true;
  env.run('syncMeetRecordings');
  assert.strictEqual(v.getDescription(), 'transcript:sent');
  assert.deepStrictEqual(env.pending('PENDING_ONBOARDING'), {});
});

test('(c2) obeval ném lỗi mạng / trả JSON hỏng / status lạ: giữ pending', () => {
  const cases = {
    throws: () => { throw new Error('network down'); },
    badjson: (u, o, r) => r(200, 'not json'),
    weird: (u, o, r) => r(200, '{"status":"mystery"}'),
    unauthorized: (u, o, r) => r(401, '{"detail":"bad token"}'),
  };
  for (const [name, obeval] of Object.entries(cases)) {
    const env = makeEnv({ fetchHandler: handlers({ weekly: webhookNever, obeval }) });
    const v = env.drive.addMeetVideo(ONB_NAME, { id: 'vid-' + name });
    env.run('syncMeetRecordings');
    assert.strictEqual(v.getDescription(), 'transcript:pending', name);
    assert.deepStrictEqual(Object.keys(env.pending('PENDING_ONBOARDING')), ['vid-' + name], name);
  }
});

// ---------- (d) unmatched ----------
test('(d) obeval unmatched: description no-match, rời hàng chờ, đúng 1 mail về ONB_ALERT_EMAIL', () => {
  const env = makeEnv({
    fetchHandler: handlers({ weekly: webhookNever, obeval: obevalStatus('unmatched', { reason: 'no_booking' }) }),
  });
  const v = env.drive.addMeetVideo(ONB_NAME, { id: 'vid-d' });
  env.run('syncMeetRecordings');
  assert.strictEqual(v.getDescription(), 'transcript:no-match');
  assert.deepStrictEqual(env.pending('PENDING_ONBOARDING'), {});
  assert.strictEqual(env.mails.length, 1);
  assert.strictEqual(env.mails[0].to, ONB_MAIL);
  assert.ok(env.mails[0].subject.startsWith('[Onboarding recording] 1 file không khớp booking'));
  assert.ok(env.mails[0].body.includes('Lý do: no_booking'));
  assert.ok(env.mails[0].body.includes('https://drive.example/vid-d'));
  assert.ok(!env.mails.some((m) => m.to === WEEKLY_MAIL));

  // lần sau không gửi lại, không mail thêm
  env.run('syncMeetRecordings');
  assert.strictEqual(env.fetches.length, 1);
  assert.strictEqual(env.mails.length, 1);
});

test('(d2) obeval ignored cũng xử như no-match', () => {
  const env = makeEnv({ fetchHandler: handlers({ weekly: webhookNever, obeval: obevalStatus('ignored', { reason: 'not_onboarding' }) }) });
  const v = env.drive.addMeetVideo(ONB_NAME, { id: 'vid-d2' });
  env.run('syncMeetRecordings');
  assert.strictEqual(v.getDescription(), 'transcript:no-match');
  assert.strictEqual(env.mails.length, 1);
  assert.ok(env.mails[0].body.includes('Lý do: not_onboarding'));
});

test('(d3) obeval duplicate: no-match + mail nói booking đã có recording được chấm, không gửi lại', () => {
  const env = makeEnv({ fetchHandler: handlers({ weekly: webhookNever, obeval: obevalStatus('duplicate', { booking_id: 'b-1' }) }) });
  const v = env.drive.addMeetVideo(ONB_NAME, { id: 'vid-d3' });
  env.run('syncMeetRecordings');
  assert.strictEqual(v.getDescription(), 'transcript:no-match');
  assert.deepStrictEqual(env.pending('PENDING_ONBOARDING'), {});
  assert.strictEqual(env.mails.length, 1);
  assert.strictEqual(env.mails[0].to, ONB_MAIL);
  assert.ok(env.mails[0].body.includes('duplicate_recording'));
  assert.ok(env.mails[0].body.includes('đã có recording được chấm'));
  env.run('syncMeetRecordings');
  assert.strictEqual(env.fetches.length, 1, 'không thử lại');
  assert.strictEqual(env.mails.length, 1);
});

// ---------- (e) folder Onboarding public ----------
for (const access of ['ANYONE_WITH_LINK', 'ANYONE', 'DOMAIN', 'DOMAIN_WITH_LINK']) {
  test('(e) folder Onboarding ' + access + ': KHÔNG chuyển file onboarding, weekly vẫn chạy', () => {
    const env = makeEnv({
      onbAccess: access,
      fetchHandler: handlers({ weekly: weeklyOk, obeval: obevalNever }),
    });
    const onb = env.drive.addMeetVideo(ONB_NAME, { id: 'vid-e-onb', name: 'onb.mp4' });
    const wk = env.drive.addMeetVideo(WEEKLY_NAME, { id: 'vid-e-wk', name: 'weekly.mp4' });
    const onbParentBefore = onb.parent;

    env.run('syncMeetRecordings');
    assert.strictEqual(onb.parent, onbParentBefore, 'file onboarding phải nằm yên');
    assert.strictEqual(onb.getDescription(), '', 'không được đánh dấu pending');
    assert.strictEqual(env.drive.onboarding.children().length, 0);
    assert.strictEqual(env.prop('PENDING_ONBOARDING'), null);
    assert.ok(env.logs.error.some((l) => l.includes('KHÔNG chuyển file')));
    assert.strictEqual(pathOf(wk), 'My Drive / Record / ' + WEEKLY_NAME + ' / weekly.mp4');
    assert.strictEqual(wk.getDescription(), 'transcript:sent');
    assert.strictEqual(env.fetches.filter((f) => f.url.startsWith(OBEVAL)).length, 0);
    assert.strictEqual(env.mails.length, 1, 'một mail báo nhánh tắt');
    assert.strictEqual(env.mails[0].to, ONB_MAIL);
    assert.ok(env.mails[0].body.includes(access), 'mail nêu lý do');
  });
}

test('(e3) folder Onboarding trong thùng rác: nhánh tắt, weekly vẫn chạy', () => {
  const env = makeEnv({ fetchHandler: handlers({ weekly: weeklyOk, obeval: obevalNever }) });
  env.drive.onboarding.trashed = true;
  const onb = env.drive.addMeetVideo(ONB_NAME, { id: 'vid-e3-onb' });
  const wk = env.drive.addMeetVideo(WEEKLY_NAME, { id: 'vid-e3-wk' });
  env.run('syncMeetRecordings');
  assert.strictEqual(onb.parent.parent, env.drive.meetRoot);
  assert.strictEqual(onb.getDescription(), '');
  assert.strictEqual(wk.getDescription(), 'transcript:sent');
  assert.strictEqual(env.mails.length, 1);
  assert.ok(env.mails[0].body.includes('thùng rác'));
});

test('(e4) chỉ PRIVATE được dùng (danh sách cho phép); giá trị lạ Drive thêm sau này cũng bị chặn', () => {
  const ok = makeEnv({ onbAccess: 'PRIVATE', fetchHandler: handlers({ weekly: webhookNever, obeval: obevalStatus('queued') }) });
  const v0 = ok.drive.addMeetVideo(ONB_NAME, { id: 'vid-e4' });
  ok.run('syncMeetRecordings');
  assert.strictEqual(v0.getDescription(), 'transcript:sent');
  assert.strictEqual(ok.mails.length, 0);

  const env = makeEnv({ onbAccess: 'SOMETHING_NEW', fetchHandler: handlers({ weekly: webhookNever, obeval: obevalNever }) });
  const v = env.drive.addMeetVideo(ONB_NAME, { id: 'vid-e4b' });
  env.run('syncMeetRecordings');
  assert.strictEqual(v.parent.parent, env.drive.meetRoot);
});

// ---------- file / thư mục đích không riêng tư ----------
test('(i) thư mục đích đã có sẵn và đang DOMAIN_WITH_LINK: không chuyển, không pending, log id (không tên), 1 mail', () => {
  const env = makeEnv({ fetchHandler: handlers({ weekly: weeklyOk, obeval: obevalNever }) });
  const dest = env.drive.addFolder(env.drive.onboarding, ONB_NAME, 'dest-leaky');
  dest.access = 'DOMAIN_WITH_LINK';
  const v = env.drive.addMeetVideo(ONB_NAME, { id: 'vid-i', name: 'secret-kid-name.mp4' });
  const wk = env.drive.addMeetVideo(WEEKLY_NAME, { id: 'vid-i-wk' });
  env.run('syncMeetRecordings');
  assert.strictEqual(v.parent.parent, env.drive.meetRoot, 'file nằm yên');
  assert.strictEqual(v.getDescription(), '', 'chưa đánh dấu pending');
  assert.deepStrictEqual(env.pending('PENDING_ONBOARDING'), {});
  assert.strictEqual(env.drive.moves.filter((m) => m.file === 'vid-i').length, 0);
  assert.ok(env.logs.error.some((l) => l.includes('vid-i') && l.includes('KHÔNG chuyển')));
  assert.ok(!env.logs.error.some((l) => l.includes('secret-kid-name')), 'log lỗi dùng id, không dùng tên file');
  assert.strictEqual(env.mails.length, 1);
  assert.strictEqual(env.mails[0].to, ONB_MAIL);
  assert.ok(!env.mails[0].body.includes('secret-kid-name') && !env.mails[0].subject.includes('secret-kid-name'));
  assert.ok(env.mails[0].subject.includes('1 file onboarding không được chuyển'));
  assert.strictEqual(wk.getDescription(), 'transcript:sent', 'weekly không ảnh hưởng');

  env.run('syncMeetRecordings'); // trong 24 giờ: không mail nữa
  assert.strictEqual(env.mails.length, 1);
  assert.strictEqual(env.fetches.filter((f) => f.url.startsWith(OBEVAL)).length, 0);
});

test('(i2) file onboarding đang DOMAIN_WITH_LINK: không chuyển, không pending, không tạo thư mục đích', () => {
  const env = makeEnv({ fetchHandler: handlers({ weekly: webhookNever, obeval: obevalNever }) });
  const v = env.drive.addMeetVideo(ONB_NAME, { id: 'vid-i2' });
  v.access = 'DOMAIN_WITH_LINK';
  env.run('syncMeetRecordings');
  assert.strictEqual(v.parent.parent, env.drive.meetRoot);
  assert.strictEqual(v.getDescription(), '');
  assert.deepStrictEqual(env.pending('PENDING_ONBOARDING'), {});
  assert.strictEqual(env.drive.onboarding.children().length, 0);
  assert.ok(env.logs.error.some((l) => l.includes('vid-i2')));
  assert.strictEqual(env.mails.length, 1);
});

// ---------- cảnh báo nhánh tắt: giới hạn 1 lần / 24 giờ ----------
test('(j) nhánh tắt: lượt đầu 1 mail, trong 24h không mail, sau 24h mail lại; mail không chứa tên file', () => {
  const env = makeEnv({ onbAccess: 'ANYONE_WITH_LINK', fetchHandler: handlers({ weekly: weeklyOk, obeval: obevalNever }) });
  env.drive.addMeetVideo(ONB_NAME, { id: 'vid-j', name: 'secret-kid-name.mp4' });
  env.run('syncMeetRecordings');
  assert.strictEqual(env.mails.length, 1);
  assert.strictEqual(env.mails[0].to, ONB_MAIL);
  assert.ok(env.mails[0].body.includes('ANYONE_WITH_LINK'));
  assert.ok(env.mails[0].body.includes('Google Meet') && env.mails[0].body.includes('backfillOldRecordings') &&
    env.mails[0].body.includes('markRecentPendingOnboarding'));
  assert.ok(!env.mails[0].body.includes('secret-kid-name') && !env.mails[0].body.includes(ONB_NAME));
  assert.ok(Math.abs(Number(env.prop('ONB_DISABLED_ALERT_AT')) - Date.now()) < 60 * 1000);

  env.run('syncMeetRecordings');
  env.run('backfillOldRecordings');
  assert.strictEqual(env.mails.length, 1, 'trong 24 giờ không gửi thêm');

  env.store.set('ONB_DISABLED_ALERT_AT', String(Date.now() - 23 * HOUR));
  env.run('syncMeetRecordings');
  assert.strictEqual(env.mails.length, 1, 'mới 23 giờ: chưa gửi');

  env.store.set('ONB_DISABLED_ALERT_AT', String(Date.now() - 25 * HOUR));
  env.run('syncMeetRecordings');
  assert.strictEqual(env.mails.length, 2, 'sau 24 giờ gửi lại');
});

test('(j2) không có ONB_ALERT_EMAIL: không mail, không ném lỗi, weekly bình thường', () => {
  const env = makeEnv({ props: { ONB_ALERT_EMAIL: null }, onbAccess: 'ANYONE', fetchHandler: handlers({ weekly: weeklyOk, obeval: obevalNever }) });
  const wk = env.drive.addMeetVideo(WEEKLY_NAME, { id: 'vid-j2' });
  env.run('syncMeetRecordings');
  assert.strictEqual(env.mails.length, 0);
  assert.strictEqual(env.prop('ONB_DISABLED_ALERT_AT'), null);
  assert.strictEqual(wk.getDescription(), 'transcript:sent');
});

test('(j3) MailApp ném lỗi khi báo nhánh tắt: lượt chạy không hỏng, weekly vẫn chạy, chưa ghi mốc throttle', () => {
  const env = makeEnv({ onbAccess: 'ANYONE', mailThrows: true, fetchHandler: handlers({ weekly: weeklyOk, obeval: obevalNever }) });
  const wk = env.drive.addMeetVideo(WEEKLY_NAME, { id: 'vid-j3' });
  env.drive.addMeetVideo(ONB_NAME, { id: 'vid-j3b' });
  assert.doesNotThrow(() => env.run('syncMeetRecordings'));
  assert.strictEqual(wk.getDescription(), 'transcript:sent');
  assert.strictEqual(env.prop('ONB_DISABLED_ALERT_AT'), null, 'gửi lỗi thì lượt sau thử lại');
  assert.ok(env.logs.error.some((l) => l.includes('không gửi được mail cảnh báo')));
});

test('(j4) mốc throttle hỏng (không phải số): vẫn gửi, không ném lỗi', () => {
  const env = makeEnv({ onbAccess: 'ANYONE', props: { ONB_DISABLED_ALERT_AT: 'rác' }, fetchHandler: handlers({ weekly: weeklyOk, obeval: obevalNever }) });
  assert.doesNotThrow(() => env.run('syncMeetRecordings'));
  assert.strictEqual(env.mails.length, 1);
});

// ---------- không có ONB_ALERT_EMAIL: danh sách vẫn lên nhật ký ----------
test('(k) không có ONB_ALERT_EMAIL: no-match và hết hạn được console.error, không mail', () => {
  const obeval = (u, o, r) => (o.payload.includes('vid-k-old') ? r(500, 'down') : r(200, '{"status":"unmatched","reason":"no_booking"}'));
  const env = makeEnv({ props: { ONB_ALERT_EMAIL: null }, fetchHandler: handlers({ weekly: webhookNever, obeval }) });
  env.drive.addMeetVideo(ONB_NAME, { id: 'vid-k', name: 'nomatch.mp4' });
  const meeting = env.drive.addFolder(env.drive.onboarding, ONB_NAME + ' old');
  env.drive.addVideoIn(meeting, { id: 'vid-k-old', name: 'expired.mp4', modifiedAgoMs: 10 * DAY });
  env.store.set('PENDING_ONBOARDING', JSON.stringify({ 'vid-k-old': Date.now() - 3 * DAY }));
  env.run('syncMeetRecordings');
  assert.strictEqual(env.mails.length, 0);
  assert.ok(env.logs.error.some((l) => l.includes('không khớp booking') && l.includes('nomatch.mp4') && l.includes('no_booking')));
  assert.ok(env.logs.error.some((l) => l.includes('bị bỏ sau 2 ngày lỗi') && l.includes('expired.mp4')));
});

// ---------- lỗi moveTo, file đã sent không vào lại hàng chờ, cache ----------
test('(l) moveTo của file onboarding ném lỗi: vẫn pending, lượt sau thử lại, quá hạn thì bị bỏ + mail "chưa chuyển được"', () => {
  const env = makeEnv({ fetchHandler: handlers({ weekly: webhookNever, obeval: obevalNever }) });
  const v = env.drive.addMeetVideo(ONB_NAME, { id: 'vid-l', name: 'stuck.mp4' });
  let attempts = 0;
  v.moveTo = () => { attempts++; throw new Error('Drive quota'); };

  env.run('syncMeetRecordings');
  assert.strictEqual(attempts, 1);
  assert.deepStrictEqual(Object.keys(env.pending('PENDING_ONBOARDING')), ['vid-l']);
  assert.strictEqual(v.getDescription(), 'transcript:pending');
  assert.ok(env.logs.error.some((l) => l.includes('vid-l') && l.includes('Drive quota')));
  assert.strictEqual(env.mails.length, 0);

  env.run('syncMeetRecordings');
  assert.strictEqual(attempts, 2, 'lượt sau thử lại');
  assert.deepStrictEqual(Object.keys(env.pending('PENDING_ONBOARDING')), ['vid-l']);

  const p = env.pending('PENDING_ONBOARDING');
  p['vid-l'] = Date.now() - 3 * DAY;
  env.store.set('PENDING_ONBOARDING', JSON.stringify(p));
  env.run('syncMeetRecordings');
  assert.deepStrictEqual(env.pending('PENDING_ONBOARDING'), {});
  assert.strictEqual(env.mails.length, 1);
  assert.ok(env.mails[0].subject.includes('bị bỏ sau 2 ngày lỗi'));
  assert.ok(env.mails[0].body.includes('chưa chuyển được sang folder Onboarding'));
  assert.strictEqual(env.fetches.length, 0);
});

test('(m) file đã sent xuất hiện lại trong lần quét sau (modifiedDate đổi): KHÔNG vào lại hàng chờ, không gửi lại', () => {
  const env = makeEnv({ fetchHandler: handlers({ weekly: weeklyOk, obeval: obevalStatus('queued') }) });
  const v = env.drive.addMeetVideo(ONB_NAME, { id: 'vid-m' });
  const wk = env.drive.addMeetVideo(WEEKLY_NAME, { id: 'vid-m-wk' });
  env.run('syncMeetRecordings');
  assert.strictEqual(v.getDescription(), 'transcript:sent');
  assert.strictEqual(wk.getDescription(), 'transcript:sent');
  const calls = env.fetches.length;
  const moves = env.drive.moves.length;
  v.modified = new Date();
  wk.modified = new Date(); // như Drive thật khi có thay đổi nhỏ
  env.run('syncMeetRecordings');
  env.run('backfillOldRecordings');
  assert.strictEqual(env.fetches.length, calls, 'không gửi lại');
  assert.strictEqual(env.drive.moves.length, moves, 'không chuyển lại');
  assert.deepStrictEqual(env.pending('PENDING_ONBOARDING'), {});
  assert.deepStrictEqual(env.pending('PENDING_RECORDINGS'), {});
  assert.strictEqual(v.getDescription(), 'transcript:sent');
});

test('(n) cache cấu hình không sống qua các lượt: folder đổi sang public giữa hai lượt thì lượt sau chặn ngay', () => {
  const env = makeEnv({ fetchHandler: handlers({ weekly: webhookNever, obeval: obevalStatus('queued') }) });
  const a = env.drive.addMeetVideo(ONB_NAME, { id: 'vid-n1' });
  env.run('syncMeetRecordings');
  assert.strictEqual(a.getDescription(), 'transcript:sent');
  env.drive.onboarding.access = 'ANYONE_WITH_LINK';
  const b = env.drive.addMeetVideo(ONB_NAME + ' 2', { id: 'vid-n2' });
  env.run('syncMeetRecordings');
  assert.strictEqual(b.parent.parent, env.drive.meetRoot);
  assert.strictEqual(b.getDescription(), '');
});

test('(o) isOnboardingMeeting chỉ chạm Drive/Properties khi tên giống onboarding', () => {
  const env = makeEnv({ fetchHandler: handlers({ weekly: webhookNever, obeval: obevalNever }) });
  const reads = [];
  const orig = env.drive.byId.bind(env.drive);
  env.drive.byId = (id) => { reads.push(id); return orig(id); };
  assert.strictEqual(env.evalIn('isOnboardingMeeting(' + JSON.stringify(OTHER_NAME) + ')'), false);
  assert.strictEqual(env.evalIn('isOnboardingMeeting(' + JSON.stringify(WEEKLY_NAME) + ')'), false);
  assert.deepStrictEqual(reads, []);
  assert.strictEqual(env.evalIn('isOnboardingMeeting(' + JSON.stringify(ONB_NAME) + ')'), true);
  assert.ok(reads.includes(ONB_ID));
});

test('(e2) folder Onboarding không đọc được (ID sai): nhánh onboarding tắt, weekly không bị ảnh hưởng', () => {
  const env = makeEnv({
    props: { ONBOARDING_FOLDER_ID: 'khong-ton-tai' },
    fetchHandler: handlers({ weekly: weeklyOk, obeval: obevalNever }),
  });
  const onb = env.drive.addMeetVideo(ONB_NAME, { id: 'vid-e2-onb' });
  const wk = env.drive.addMeetVideo(WEEKLY_NAME, { id: 'vid-e2-wk' });
  env.run('syncMeetRecordings');
  assert.strictEqual(onb.parent.name, ONB_NAME);
  assert.strictEqual(onb.parent.parent, env.drive.meetRoot);
  assert.strictEqual(wk.getDescription(), 'transcript:sent');
  assert.ok(env.logs.error.some((l) => l.includes('không đọc được folder Onboarding')));
});

// ---------- (f) thiếu cấu hình ----------
for (const missing of ['OBEVAL_URL', 'OBEVAL_TOKEN', 'ONBOARDING_FOLDER_ID']) {
  test('(f) thiếu ' + missing + ': onboarding tắt (không move, không HTTP), weekly bình thường', () => {
    const env = makeEnv({
      props: { [missing]: null },
      fetchHandler: handlers({ weekly: weeklyOk, obeval: obevalNever }),
    });
    const onb = env.drive.addMeetVideo(ONB_NAME, { id: 'vid-f-onb' });
    const wk = env.drive.addMeetVideo(WEEKLY_NAME, { id: 'vid-f-wk' });
    env.run('syncMeetRecordings');
    assert.strictEqual(onb.parent.parent, env.drive.meetRoot, 'file onboarding nằm yên trong Google Meet');
    assert.strictEqual(onb.getDescription(), '');
    assert.strictEqual(env.prop('PENDING_ONBOARDING'), null);
    assert.ok(env.logs.error.some((l) => l.includes('thiếu Script Properties')));
    assert.strictEqual(env.mails.length, 1, 'báo nhánh tắt qua ONB_ALERT_EMAIL');
    assert.strictEqual(env.mails[0].to, ONB_MAIL);
    assert.strictEqual(pathOf(wk), 'My Drive / Record / ' + WEEKLY_NAME + ' / ' + wk.name);
    assert.strictEqual(wk.getDescription(), 'transcript:sent');
    assert.strictEqual(env.fetches.length, 1);
    assert.strictEqual(env.fetches[0].url, WEBHOOK);
  });
}

test('(f2) không cấu hình onboarding gì cả + chỉ có weekly: y hệt script cũ', () => {
  const env = makeEnv({ onbProps: false, fetchHandler: handlers({ weekly: weeklyOk, obeval: obevalNever }) });
  const wk = env.drive.addMeetVideo(WEEKLY_NAME, { id: 'vid-f2' });
  env.run('syncMeetRecordings');
  assert.strictEqual(wk.getDescription(), 'transcript:sent');
  assert.deepStrictEqual(env.fetches.map((f) => f.url), [WEBHOOK]);
  assert.strictEqual(env.mails.length, 0);
});

// ---------- (g) tên thư mục không khớp ----------
test('(g) thư mục buổi họp khớp cả hai mẫu không: không đụng tới', () => {
  const env = makeEnv({ fetchHandler: handlers({ weekly: webhookNever, obeval: obevalNever }) });
  const v = env.drive.addMeetVideo(OTHER_NAME, { id: 'vid-g', name: 'other.mp4' });
  // mẫu gần giống nhưng sai: thiếu mã TC, sai loại buổi
  const v2 = env.drive.addMeetVideo('TeenCare - Gia sư tâm lý 1:1 Onboarding - không có mã', { id: 'vid-g2' });
  const v3 = env.drive.addMeetVideo('TeenCare - Gia sư Mentor 1:1 hàng tuần - thiếu mã', { id: 'vid-g3' });
  env.run('syncMeetRecordings');
  for (const x of [v, v2, v3]) {
    assert.strictEqual(x.parent.parent, env.drive.meetRoot);
    assert.strictEqual(x.getDescription(), '');
  }
  assert.strictEqual(env.drive.moves.length, 0);
  assert.strictEqual(env.fetches.length, 0);
  assert.deepStrictEqual(env.pending('PENDING_RECORDINGS'), {});
  assert.deepStrictEqual(env.pending('PENDING_ONBOARDING'), {});
});

test('(g2) buổi onboarding nằm ngoài thư mục "Google Meet" đang dùng (vd. thư mục Meet public cũ) bị bỏ qua', () => {
  const env = makeEnv({ fetchHandler: handlers({ weekly: webhookNever, obeval: obevalNever }) });
  env.drive.meetRoot.access = 'ANYONE_WITH_LINK'; // root "Google Meet" đã public → không phải root đang dùng
  const v = env.drive.addMeetVideo(ONB_NAME, { id: 'vid-g4' });
  env.run('syncMeetRecordings');
  assert.strictEqual(v.parent.parent, env.drive.meetRoot);
  assert.strictEqual(env.fetches.length, 0);
});

// ---------- (h) hết hạn ----------
test('(h) pending quá SEND_MAX_AGE_DAYS vẫn lỗi: bị bỏ khỏi PENDING_ONBOARDING và báo trong mail hết hạn', () => {
  const env = makeEnv({ fetchHandler: handlers({ weekly: webhookNever, obeval: (u, o, r) => r(500, 'still down') }) });
  const meeting = env.drive.addFolder(env.drive.onboarding, ONB_NAME);
  const v = env.drive.addVideoIn(meeting, { id: 'vid-h', name: 'old.mp4', modifiedAgoMs: 10 * DAY, createdAgoMs: 3 * DAY });
  v.setDescription('transcript:pending');
  env.store.set('PENDING_ONBOARDING', JSON.stringify({ 'vid-h': Date.now() - 3 * DAY }));

  env.run('syncMeetRecordings');
  assert.deepStrictEqual(env.pending('PENDING_ONBOARDING'), {});
  assert.strictEqual(v.getDescription(), 'transcript:pending', 'không bị đánh dấu sent');
  assert.strictEqual(env.mails.length, 1);
  assert.strictEqual(env.mails[0].to, ONB_MAIL);
  assert.ok(env.mails[0].subject.startsWith('[Onboarding recording] 1 file bị bỏ sau 2 ngày lỗi'));
  assert.ok(env.mails[0].body.includes('old.mp4'));
  assert.ok(env.mails[0].body.includes('HTTP 500'));
  assert.strictEqual(env.fetches.length, 1);
});

test('(h2) pending CHƯA quá hạn vẫn lỗi: giữ lại, không mail', () => {
  const env = makeEnv({ fetchHandler: handlers({ weekly: webhookNever, obeval: (u, o, r) => r(500, 'down') }) });
  const meeting = env.drive.addFolder(env.drive.onboarding, ONB_NAME);
  env.drive.addVideoIn(meeting, { id: 'vid-h2', modifiedAgoMs: 10 * DAY });
  env.store.set('PENDING_ONBOARDING', JSON.stringify({ 'vid-h2': Date.now() - 1 * DAY }));
  env.run('syncMeetRecordings');
  assert.deepStrictEqual(Object.keys(env.pending('PENDING_ONBOARDING')), ['vid-h2']);
  assert.strictEqual(env.mails.length, 0);
});

test('(h3) pending quá hạn mà file chưa tới folder Onboarding: bỏ và báo "chưa chuyển được"', () => {
  const env = makeEnv({ fetchHandler: handlers({ weekly: webhookNever, obeval: obevalNever }) });
  const v = env.drive.addMeetVideo(ONB_NAME, { id: 'vid-h3', modifiedAgoMs: 10 * DAY });
  env.store.set('PENDING_ONBOARDING', JSON.stringify({ 'vid-h3': Date.now() - 3 * DAY }));
  env.run('syncMeetRecordings');
  assert.deepStrictEqual(env.pending('PENDING_ONBOARDING'), {});
  assert.strictEqual(env.mails.length, 1);
  assert.ok(env.mails[0].body.includes('chưa chuyển được sang folder Onboarding'));
  assert.strictEqual(env.fetches.length, 0);
  assert.ok(v);
});

// ---------- khác ----------
test('hai nhánh cùng một lượt: weekly và onboarding đi đúng nơi, hàng chờ tách biệt', () => {
  const env = makeEnv({
    fetchHandler: handlers({ weekly: weeklyDown, obeval: (u, o, r) => r(500, 'down') }),
  });
  env.drive.addMeetVideo(WEEKLY_NAME, { id: 'vid-m-wk' });
  env.drive.addMeetVideo(ONB_NAME, { id: 'vid-m-onb' });
  env.run('syncMeetRecordings');
  assert.deepStrictEqual(Object.keys(env.pending('PENDING_RECORDINGS')), ['vid-m-wk']);
  assert.deepStrictEqual(Object.keys(env.pending('PENDING_ONBOARDING')), ['vid-m-onb']);
});

test('backfillOldRecordings cũng gọi nhánh onboarding', () => {
  const env = makeEnv({ fetchHandler: handlers({ weekly: weeklyOk, obeval: obevalStatus('queued') }) });
  const old = env.drive.addMeetVideo(ONB_NAME, { id: 'vid-bf', modifiedAgoMs: 20 * DAY, createdAgoMs: 20 * DAY });
  env.run('backfillOldRecordings');
  assert.strictEqual(pathOf(old).startsWith('My Drive / Onboarding recordings / '), true);
  // file cũ hơn SEND_MAX_AGE_DAYS: chỉ chuyển, không vào hàng chờ → không gửi
  assert.strictEqual(env.prop('PENDING_ONBOARDING'), JSON.stringify({}));
  assert.strictEqual(env.fetches.length, 0);
});

test('markRecentPendingOnboarding: đưa lại mọi file trong folder Onboarding vào hàng chờ, kể cả file đã sent', () => {
  const env = makeEnv({ fetchHandler: handlers({ weekly: webhookNever, obeval: obevalStatus('queued') }) });
  const meeting = env.drive.addFolder(env.drive.onboarding, ONB_NAME);
  const a = env.drive.addVideoIn(meeting, { id: 'vid-mk-a' });
  const b = env.drive.addVideoIn(meeting, { id: 'vid-mk-b' });
  b.setDescription('transcript:sent');
  a.setDescription('transcript:no-match');
  env.run('markRecentPendingOnboarding');
  assert.deepStrictEqual(Object.keys(env.pending('PENDING_ONBOARDING')).sort(), ['vid-mk-a', 'vid-mk-b']);
  assert.strictEqual(a.getDescription(), 'transcript:pending');
  assert.strictEqual(b.getDescription(), 'transcript:pending');
  env.run('sendPendingOnboarding');
  assert.strictEqual(a.getDescription(), 'transcript:sent');
  assert.strictEqual(b.getDescription(), 'transcript:sent');
  assert.deepStrictEqual(env.pending('PENDING_ONBOARDING'), {});
});

test('markRecentPendingOnboarding: file MARK_SENT trong folder Onboarding được gửi lại (cứu ca kẹt processing); register idempotent', () => {
  const env = makeEnv({ fetchHandler: handlers({ weekly: webhookNever, obeval: obevalStatus('in_progress') }) });
  const meeting = env.drive.addFolder(env.drive.onboarding, ONB_NAME);
  const v = env.drive.addVideoIn(meeting, { id: 'vid-mk-sent' });
  v.setDescription('transcript:sent');
  env.run('markRecentPendingOnboarding');
  assert.deepStrictEqual(Object.keys(env.pending('PENDING_ONBOARDING')), ['vid-mk-sent']);
  assert.strictEqual(v.getDescription(), 'transcript:pending');
  env.run('sendPendingOnboarding');
  assert.strictEqual(env.fetches.length, 1);
  assert.strictEqual(v.getDescription(), 'transcript:sent');
  assert.deepStrictEqual(env.pending('PENDING_ONBOARDING'), {});
});

test('getPending/setPending/addPending: không đối số vẫn dùng khoá cũ PENDING_RECORDINGS', () => {
  const env = makeEnv({ fetchHandler: handlers({ weekly: webhookNever, obeval: obevalNever }) });
  env.evalIn("addPending('legacy-id'); addPending('onb-id', 'PENDING_ONBOARDING'); setPending({z: 1}, 'OTHER');");
  assert.deepStrictEqual(Object.keys(env.pending('PENDING_RECORDINGS')), ['legacy-id']);
  assert.deepStrictEqual(Object.keys(env.pending('PENDING_ONBOARDING')), ['onb-id']);
  assert.deepStrictEqual(env.pending('OTHER'), { z: 1 });
  assert.strictEqual(env.evalIn("JSON.stringify(Object.keys(getPending()))"), '["legacy-id"]');
});

test('onboarding.gs không chứa ID/URL/token thật: chỉ đọc từ Script Properties', () => {
  assert.ok(!/https?:\/\//.test(ONB.replace(/https:\/\/drive\.google\.com\/file\/d\//, '')), 'không có URL cứng');
  assert.ok(!/[A-Za-z0-9_-]{25,}/.test(ONB.replace(/[A-Za-z_]{25,}/g, '')), 'không có chuỗi giống ID/token');
  for (const k of ['ONBOARDING_FOLDER_ID', 'OBEVAL_URL', 'OBEVAL_TOKEN', 'ONB_ALERT_EMAIL']) assert.ok(ONB.includes("'" + k + "'"));
  assert.ok(/<PUBLIC_FOLDER_ID>/.test(CODE) && /<SESSION_ON_TRIGGER_DRIVE_WEBHOOK_URL>/.test(CODE) && /<ALERT_EMAIL>/.test(CODE));
});

console.log('\n' + passed + ' passed, ' + failures.length + ' failed');
if (failures.length) {
  console.log('Failed: ' + failures.join(' | '));
  process.exit(1);
}
