"""Đầu ra B — bảng điều khiển Command Center: chỉ số tổng hợp, KHÔNG xếp hạng, KHÔNG tên Mentor.

Mỗi ca ghi một `dashboard_row.json` (không tên, không trích lời). Trang HTML tự lọc theo ngày bằng JS.
"""
from __future__ import annotations

import hashlib
import html
import json
import shutil
from datetime import datetime
from pathlib import Path

# Trường được phép đi vào bảng điều khiển. Thêm trường mới phải giữ nguyên tắc: không định danh người.
ROW_FIELDS = ("case_key", "session_date", "processed_at", "status", "classification", "overall",
              "activity_scores", "ne_ratio", "deviated_steps", "flags", "sequence_status",
              "improvement_steps", "transcript_coverage", "detail_url")
DETAIL_DIR = "chi-tiet"  # bản chép detail.html theo mã ca đã băm: link trên bảng không lộ tên thư mục ca


def anon_key(case_key: str) -> str:
    """Mã ca trên bảng điều khiển: băm từ tên thư mục ca (tên file có thể chứa tên Mentor/học sinh)."""
    return "ca-" + hashlib.sha1(case_key.encode("utf-8")).hexdigest()[:8]


def make_row(case_key: str, meta: dict, result: dict | None, scores: dict | None, status: str, names) -> dict:
    """Chỉ nhận mã nằm trong danh mục và lấy tên từ danh mục — không bao giờ chép chữ tự do của model."""
    row = {k: None for k in ROW_FIELDS}
    row.update({
        "case_key": anon_key(case_key),
        "session_date": meta.get("session_date"),
        "processed_at": datetime.now().isoformat(timespec="seconds"),
        "status": status,
        "detail_url": _safe_url(meta.get("detail_url")),
    })
    if result and scores:
        row.update({
            "classification": scores["classification"],
            "overall": scores["overall"],
            "activity_scores": {str(a["activity"]): a["score"] for a in scores["activities"]},
            "ne_ratio": round(scores["ne_ratio"], 3),
            "deviated_steps": [{"id": c["id"], "name": names.crit[c["id"]]["name"], "status": c["status"]}
                               for c in result["criteria"] if c["status"] in ("NF", "PF") and c["id"] in names.crit],
            "flags": [{"id": f["id"], "name": names.flag[f["id"]]["name"], "script_instructed": bool(f.get("script_instructed"))}
                      for f in result.get("flags") or [] if f.get("id") in names.flag],
            "sequence_status": (result.get("sequence") or {}).get("status"),
            "improvement_steps": [{"id": it["criterion_id"], "name": names.crit[it["criterion_id"]]["name"]}
                                  for it in result.get("improvements") or [] if it.get("criterion_id") in names.crit],
            "transcript_coverage": (result.get("data_quality") or {}).get("transcript_coverage"),
        })
    return {k: row[k] for k in ROW_FIELDS}


def _safe_url(url) -> str | None:
    """Chỉ nhận đường dẫn https do hệ thống cấp (trang có phân quyền); còn lại dùng bản chép trong DETAIL_DIR."""
    return url if isinstance(url, str) and url.startswith("https://") and "<" not in url else None


def publish_details(out_root: Path) -> int:
    """Chép detail.html của mỗi ca sang <out_root>/chi-tiet/<mã ca>.html để bảng điều khiển link tới."""
    dst = Path(out_root) / DETAIL_DIR
    n = 0
    for f in sorted(Path(out_root).glob("*/detail.html")):
        if not (f.parent / "dashboard_row.json").exists():
            continue
        dst.mkdir(exist_ok=True)
        shutil.copyfile(f, dst / f"{anon_key(f.parent.name)}.html")
        n += 1
    return n


def collect(out_root: Path, names=None) -> list[dict]:
    rows = []
    for f in sorted(Path(out_root).glob("*/dashboard_row.json")):
        try:
            row = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            print(f"Cảnh báo: bỏ qua {f} ({exc})")
            continue
        row = {k: row.get(k) for k in ROW_FIELDS}
        row["detail_url"] = _safe_url(row.get("detail_url"))
        if not str(row.get("case_key") or "").startswith("ca-"):  # dòng do bản cũ ghi: băm lại khi đọc
            row["case_key"] = anon_key(str(row.get("case_key") or f.parent.name))
        if names is not None:  # dựng lại tên từ danh mục, bỏ mã lạ (dòng cũ có thể chứa chữ tự do)
            row["deviated_steps"] = [{"id": s.get("id"), "name": names.crit[s["id"]]["name"], "status": s.get("status")}
                                     for s in row.get("deviated_steps") or [] if s.get("id") in names.crit]
            row["improvement_steps"] = [{"id": s.get("id"), "name": names.crit[s["id"]]["name"]}
                                        for s in row.get("improvement_steps") or [] if s.get("id") in names.crit]
            row["flags"] = [{"id": s.get("id"), "name": names.flag[s["id"]]["name"], "script_instructed": bool(s.get("script_instructed"))}
                            for s in row.get("flags") or [] if s.get("id") in names.flag]
            for key, allowed in (("transcript_coverage", ("full", "partial", "poor")),
                                 ("sequence_status", ("DUNG_THU_TU", "LECH_NHE", "LECH_NGHIEM_TRONG", "KHONG_DU_DU_LIEU")),
                                 ("classification", ("TUAN_THU_TOT", "CHECH_KICH_BAN", "THIEU_DU_LIEU")),
                                 ("status", ("done", "error", "processing"))):
                if row.get(key) not in allowed:
                    row[key] = None
        rows.append(row)
    return rows


def _embed(obj) -> str:
    """JSON an toàn trong <script>: thoát mọi '<' (chặn </script>, <!--)."""
    return json.dumps(obj, ensure_ascii=False).replace("<", "\\u003c")


_PAGE = r"""<!doctype html>
<html lang="vi"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Chất lượng onboarding</title>
<style>
:root{--bg:#f7f7f5;--card:#fff;--ink:#1f1f1f;--muted:#666;--line:#e3e3e3;--good:#1e7b4a;--warn:#b26a00;--grey:#6b6b6b;--bar:#3b6ea5}
body{margin:0;background:var(--bg);color:var(--ink);font-family:Arial,Helvetica,sans-serif}
main{max-width:1100px;margin:0 auto;padding:16px}
h1{font-size:22px;margin:4px 0 2px} .sub{color:var(--muted);font-size:13px;margin-bottom:12px}
.filters{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin:10px 0 16px}
.filters button{border:1px solid var(--line);background:var(--card);padding:6px 10px;border-radius:6px;cursor:pointer}
.filters button.on{background:var(--ink);color:#fff}
.filters input,.filters select{padding:5px;border:1px solid var(--line);border-radius:6px}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:10px}
.card{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:12px}
.card .v{font-size:26px;font-weight:bold} .card .l{color:var(--muted);font-size:13px}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-top:12px}
@media(max-width:760px){.grid2{grid-template-columns:1fr}}
.panel{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:12px}
.panel h2{font-size:16px;margin:0 0 8px}
.row{display:flex;align-items:center;gap:8px;margin:5px 0;font-size:13px}
.row .n{flex:1} .row .b{height:10px;background:var(--bar);border-radius:3px} .row .c{width:44px;text-align:right;color:var(--muted)}
.note{color:var(--muted);font-size:12px;margin-top:14px}
.full{margin-top:12px} table.cases{border-collapse:collapse;width:100%;font-size:13px}
table.cases td,table.cases th{border-bottom:1px solid var(--line);padding:6px 8px;text-align:left;vertical-align:top}
table.cases th{color:var(--muted);font-weight:normal} .low{color:var(--warn);font-weight:bold}
.tip{font-size:13px;margin:8px 0} .tip ul{margin:4px 0 0 18px;padding:0;color:var(--muted)}
</style></head><body><main>
<h1>Chất lượng buổi onboarding — Command Center</h1>
<div class="sub">Chỉ số tổng hợp. Không xếp hạng, không hiển thị tên Mentor. Cập nhật: __GENERATED__ · ngưỡng tuân thủ tốt __THRESHOLD__</div>
<div class="filters" id="f">
 <button data-r="today">Hôm nay</button><button data-r="yesterday">Hôm qua</button>
 <button data-r="7">7 ngày</button><button data-r="30">30 ngày</button><button data-r="all" class="on">Tất cả</button>
 <span>Từ <input type="date" id="d1"> đến <input type="date" id="d2"></span>
 <select id="st"><option value="">Mọi trạng thái xử lý</option><option value="done">Đã chấm</option><option value="error">Lỗi xử lý</option><option value="processing">Đang xử lý / bị dừng</option></select>
</div>
<div class="cards" id="cards"></div>
<div class="panel full"><h2>Ca dưới chuẩn (follow kịch bản dưới __THRESHOLD__)</h2><div id="lowcases"></div></div>
<div class="grid2">
 <div class="panel"><h2>Các phần hay bị sai kịch bản nhất (số ca)</h2><div id="steps"></div></div>
 <div class="panel"><h2>Tỷ lệ thực hiện trung bình theo hoạt động</h2><div id="acts"></div></div>
 <div class="panel"><h2>Xu hướng theo tuần (tỷ lệ tuân thủ trung bình)</h2><div id="trend"></div></div>
 <div class="panel"><h2>Cờ hành vi (số ca)</h2><div id="flags"></div></div>
</div>
<div class="panel full"><h2>Đề xuất cải thiện (3 phần được góp ý nhiều nhất)</h2><div id="train"></div></div>
<div class="note">Ca thiếu dữ liệu được tính riêng, không tính là 0%. Điểm tuân thủ kịch bản không đồng nghĩa với chất lượng sư phạm hay tỷ lệ đăng ký. Cờ "theo kịch bản" là hành vi có trong kịch bản nhưng brief yêu cầu gắn cờ — chờ bộ phận học thuật chốt.</div>
</main>
<script>
const ROWS = __ROWS__;
const ACTS = __ACTS__;
const GOOD = __GOOD__;
const STEPS = __STEPS__;
const $ = id => document.getElementById(id);
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const pct = x => x == null ? "—" : Math.round(x * 100) + "%";
const day = r => (r.session_date || (r.processed_at || "").slice(0, 10));
let range = "all";
const iso = x => x.getFullYear() + "-" + String(x.getMonth() + 1).padStart(2, "0") + "-" + String(x.getDate()).padStart(2, "0");
function inRange(r) {
  const d = day(r); if (!d) return range === "all";
  const today = new Date();
  const back = n => { const t = new Date(today); t.setDate(t.getDate() - n); return iso(t); };
  if (range === "today") return d === iso(today);
  if (range === "yesterday") return d === back(1);
  if (range === "7") return d >= back(6);
  if (range === "30") return d >= back(29);
  if (range === "custom") { const a = $("d1").value, b = $("d2").value; return (!a || d >= a) && (!b || d <= b); }
  return true;
}
function bars(el, items, max, fmt) {
  el.innerHTML = items.length ? items.map(([n, v, extra]) =>
    `<div class="row"><span class="n">${esc(n)}${extra ? ' <span style="color:#666">' + esc(extra) + '</span>' : ''}</span>` +
    `<span class="b" style="width:${Math.max(4, 160 * v / (max || 1))}px"></span><span class="c">${fmt(v)}</span></div>`).join("")
    : '<div class="row" style="color:#666">Chưa có dữ liệu</div>';
}
function render() {
  const st = $("st").value;
  const rows = ROWS.filter(inRange).filter(r => !st || r.status === st);
  const done = rows.filter(r => r.status === "done");
  const good = done.filter(r => r.classification === "TUAN_THU_TOT").length;
  const dev = done.filter(r => r.classification === "CHECH_KICH_BAN").length;
  const insuf = done.filter(r => r.classification === "THIEU_DU_LIEU").length;
  const scored = done.filter(r => r.classification !== "THIEU_DU_LIEU" && r.overall != null);
  const avg = scored.length ? scored.reduce((s, r) => s + r.overall, 0) / scored.length : null;
  const errs = rows.filter(r => r.status === "error").length;
  const share = n => done.length ? ` (${Math.round(100 * n / done.length)}%)` : "";
  $("cards").innerHTML = [
    ["Tổng số ca", rows.length], ["Tỷ lệ follow kịch bản TB", pct(avg)],
    ["Ca follow kịch bản (≥ " + pct(GOOD) + ")", good + share(good)], ["Ca không follow (< " + pct(GOOD) + ")", dev + share(dev)],
    ["Ca thiếu dữ liệu", insuf + share(insuf)], ["Lỗi / đang xử lý", errs + " / " + rows.filter(r => r.status === "processing").length]
  ].map(([l, v]) => `<div class="card"><div class="v">${v}</div><div class="l">${l}</div></div>`).join("");
  const low = scored.filter(r => r.overall < GOOD).sort((a, b) => a.overall - b.overall);
  $("lowcases").innerHTML = low.length ? '<table class="cases"><tr><th>Ngày</th><th>Mã ca</th><th>Follow kịch bản</th>' +
    '<th>Hoạt động thấp nhất</th><th>Số phần chưa làm / làm một phần</th><th></th></tr>' + low.map(r => {
      const a = ACTS.map(x => [x, (r.activity_scores || {})[x.id]]).filter(x => x[1] != null).sort((p, q) => p[1] - q[1])[0];
      const ds = r.deviated_steps || [];
      const href = r.detail_url || ("chi-tiet/" + encodeURIComponent(r.case_key) + ".html");
      return `<tr><td>${esc(day(r))}</td><td>${esc(r.case_key)}</td><td class="low">${pct(r.overall)}</td>` +
        `<td>${a ? esc(a[0].id + ". " + a[0].name) + " (" + pct(a[1]) + ")" : "—"}</td>` +
        `<td>${ds.filter(s => s.status === "NF").length} / ${ds.filter(s => s.status === "PF").length}</td>` +
        `<td><a href="${esc(href)}" target="_blank" rel="noopener">Xem chi tiết</a></td></tr>`; }).join("") + "</table>"
    : '<div class="row" style="color:#666">Không có ca nào dưới chuẩn trong khoảng đã chọn</div>';
  // Ca thiếu dữ liệu chỉ đếm riêng, không góp vào thống kê bước chệch / cờ / chủ đề đào tạo.
  const cnt = {}; scored.forEach(r => (r.deviated_steps || []).forEach(s => { cnt[s.name] = (cnt[s.name] || 0) + 1; }));
  const top = Object.entries(cnt).sort((a, b) => b[1] - a[1]).slice(0, 10);
  bars($("steps"), top, top.length ? top[0][1] : 1, v => v);
  const acts = ACTS.map(a => { const v = scored.map(r => (r.activity_scores || {})[a.id]).filter(x => x != null);
    return [a.id + ". " + a.name, v.length ? v.reduce((s, x) => s + x, 0) / v.length : 0, v.length ? "" : "(chưa có)"]; });
  bars($("acts"), acts, 1, pct);
  const wk = {}; scored.forEach(r => { const d = new Date(day(r)); if (isNaN(d)) return; const m = new Date(d); m.setDate(d.getDate() - ((d.getDay() + 6) % 7));
    const k = iso(m); (wk[k] = wk[k] || []).push(r.overall); });
  const trend = Object.keys(wk).sort().map(k => ["Tuần từ " + k, wk[k].reduce((s, x) => s + x, 0) / wk[k].length, wk[k].length + " ca"]);
  bars($("trend"), trend, 1, pct);
  const tr = {}; scored.forEach(r => (r.improvement_steps || []).forEach(s => { tr[s.id] = (tr[s.id] || 0) + 1; }));
  const t3 = Object.entries(tr).sort((a, b) => b[1] - a[1]).slice(0, 3);
  // Chữ "cần làm" lấy từ danh mục tiêu chí của brief, không từ lời model (có thể chứa tên gia đình).
  $("train").innerHTML = t3.length ? t3.map(([id, n], i) => { const st = STEPS[id] || {name: id, reqs: []};
    return `<div class="tip"><b>${i + 1}. ${esc(st.name)}</b> <span style="color:#666">— góp ý ở ${n} ca</span>` +
      (st.reqs.length ? "<ul>" + st.reqs.map(x => "<li>" + esc(x) + "</li>").join("") + "</ul>" : "") + "</div>"; }).join("")
    : '<div class="row" style="color:#666">Chưa có dữ liệu</div>';
  const fl = {}; scored.forEach(r => (r.flags || []).forEach(f => { const k = f.name + (f.script_instructed ? " (theo kịch bản)" : ""); fl[k] = (fl[k] || 0) + 1; }));
  const fs = Object.entries(fl).sort((a, b) => b[1] - a[1]);
  bars($("flags"), fs, fs.length ? fs[0][1] : 1, v => v);
}
document.querySelectorAll("#f button").forEach(b => b.onclick = () => {
  document.querySelectorAll("#f button").forEach(x => x.classList.remove("on")); b.classList.add("on"); range = b.dataset.r; render(); });
["d1", "d2"].forEach(id => $(id).onchange = () => { document.querySelectorAll("#f button").forEach(x => x.classList.remove("on")); range = "custom"; render(); });
$("st").onchange = render;
render();
</script></body></html>
"""


def build_html(rows: list[dict], activities: list[dict], good_threshold: float, criteria: list[dict] | None = None) -> str:
    acts = [{"id": str(a["id"]), "name": a["name"]} for a in activities]
    steps = {c["id"]: {"name": c["name"], "reqs": list(c.get("requirements") or [])} for c in criteria or []}
    page = _PAGE
    page = page.replace("__GENERATED__", html.escape(datetime.now().strftime("%d/%m/%Y %H:%M")))
    page = page.replace("__THRESHOLD__", f"{good_threshold * 100:.0f}%")
    page = page.replace("__ROWS__", _embed(rows))
    page = page.replace("__ACTS__", _embed(acts))
    page = page.replace("__GOOD__", json.dumps(good_threshold))
    page = page.replace("__STEPS__", _embed(steps))
    return page
