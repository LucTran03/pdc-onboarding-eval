"""Đầu ra A — email góp ý riêng cho Mentor (HTML + text + .eml chưa gửi), và trang chi tiết để kiểm định."""
from __future__ import annotations

import html
import re
from email.message import EmailMessage

from .score import pct

STATUS_LABEL = {"FF": "Làm đủ", "PF": "Làm một phần", "NF": "Chưa làm", "NA": "Không áp dụng", "NE": "Không đủ dữ liệu"}
STATUS_COLOR = {"FF": "#1e7b4a", "PF": "#b26a00", "NF": "#b3261e", "NA": "#6b6b6b", "NE": "#6b6b6b"}
LINK_LABEL = {"DAT": "Đạt", "DAT_MOT_PHAN": "Đạt một phần", "CHUA_DAT": "Chưa đạt", "KHONG_DU_DU_LIEU": "Không đủ dữ liệu"}
SEQ_LABEL = {"DUNG_THU_TU": "Đúng thứ tự", "LECH_NHE": "Lệch nhẹ", "LECH_NGHIEM_TRONG": "Lệch nghiêm trọng", "KHONG_DU_DU_LIEU": "Không đủ dữ liệu"}
SEV_LABEL = {"high": "Cao", "medium": "Trung bình", "low": "Thấp"}
COVERAGE_LABEL = {"full": "đủ cả buổi", "partial": "thiếu một phần", "poor": "thiếu nhiều"}
SCRIPT_NOTE = "hành vi này có trong kịch bản; bộ phận học thuật đang xem lại cách đánh giá"
DISCLAIMER = ("Điểm tuân thủ kịch bản không đồng nghĩa với chất lượng sư phạm hay việc gia đình có đăng ký hay không. "
              "Báo cáo do AI tạo từ transcript nên có thể sai ở những đoạn nghe không rõ — nếu thấy chỗ nào chưa đúng, "
              "thầy/cô phản hồi giúp bộ phận học thuật.")

e = html.escape


class Names:
    def __init__(self, criteria_doc: dict):
        self.crit = {c["id"]: c for c in criteria_doc["criteria"]}
        self.act = {a["id"]: a for a in criteria_doc["activities"]}
        self.link = {lk["id"]: lk for lk in criteria_doc["links"]}
        self.flag = {f["id"]: f for f in criteria_doc["flags"]}

    def step(self, cid: str | None, fallback: str = "") -> str:
        c = self.crit.get(str(cid or "").upper())
        return c["name"] if c else (fallback or str(cid or ""))

    def act_name(self, a: int) -> str:
        return f"Hoạt động {a}. {self.act[a]['name']}" if a in self.act else f"Hoạt động {a}"

    def act_of(self, cid: str) -> int | None:
        c = self.crit.get(cid)
        return c["activity"] if c else None

    _CODE_RE = re.compile(r"\b(OB\d{2}|LK0\d|F(?:0\d|10))\b")

    def humanize(self, text) -> str:
        """Thay mã nội bộ trong câu chữ của model bằng tên bước ("(OB28)" → "(bước “Nhắc lại…”)").

        Chỉ thay chính mã, giữ nguyên ngoặc / dấu phẩy xung quanh ("(OB27, OB28)" vẫn cân ngoặc).
        """
        def _sub(m):
            code = m.group(1)
            name = (self.crit.get(code) or self.link.get(code) or self.flag.get(code) or {}).get("name")
            if not name:
                return m.group(0)
            return f"bước “{name}”" if code.startswith("OB") else f"“{name.rstrip('.')}”"
        return self._CODE_RE.sub(_sub, str(text or ""))


def _ev_line(ev: dict) -> str:
    who = ev.get("speaker") or ""
    return f"[{ev.get('timestamp', '')}] {who + ': ' if who else ''}“{ev.get('quote', '')}”"


def _verified(evs) -> list[dict]:
    """Chỉ trích dẫn đã khớp transcript (verify.py đã tách, đây là lớp chặn thứ hai)."""
    return [ev for ev in evs or [] if isinstance(ev, dict) and ev.get("verified") is not False]


def _first_ev(item: dict) -> dict:
    evs = _verified(item.get("evidence"))
    return evs[0] if evs else {}


def _first_ts(evs) -> str:
    for ev in _verified(evs):
        if ev.get("timestamp"):
            return str(ev["timestamp"])
    return ""


def _deviations(result: dict) -> list[dict]:
    """Tiêu chí NF trước, rồi PF; trong mỗi nhóm theo thứ tự kịch bản."""
    rows = [c for c in result["criteria"] if c["status"] in ("NF", "PF")]
    return sorted(rows, key=lambda c: (0 if c["status"] == "NF" else 1, c["id"]))


def _timeline(result: dict) -> dict[int, dict]:
    out = {}
    for t in result.get("activities_timeline") or []:
        try:
            out[int(t.get("activity"))] = t
        except (TypeError, ValueError):
            continue
    return out


def subject(meta: dict, scores: dict) -> str:
    date = meta.get("session_date") or ""
    head = f"Góp ý buổi onboarding {date}".strip()
    if scores["classification"] == "THIEU_DU_LIEU":
        return f"{head} — chưa đủ dữ liệu để chấm đầy đủ"
    return f"{head} — tuân thủ kịch bản {pct(scores['overall'])}"


# ------------------------------------------------------------------ email Mentor (HTML)

_CSS_TABLE = "border-collapse:collapse;width:100%;font-size:14px"
_CSS_TD = "border:1px solid #ddd;padding:6px 8px;vertical-align:top"


def mentor_email_page(result: dict, scores: dict, meta: dict, names: Names) -> str:
    """Email HTML bọc thành trang đầy đủ (khai báo UTF-8) để mở thẳng bằng trình duyệt."""
    return ("<!doctype html><html lang='vi'><head><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width,initial-scale=1'>"
            f"<title>{e(subject(meta, scores))}</title></head><body style='background:#fff;margin:16px'>"
            + mentor_email_html(result, scores, meta, names) + "</body></html>")


def mentor_email_html(result: dict, scores: dict, meta: dict, names: Names) -> str:
    greet = meta.get("mentor_name")
    tl = _timeline(result)
    p = []
    p.append('<div style="font-family:Arial,Helvetica,sans-serif;max-width:720px;color:#1f1f1f;line-height:1.5">')
    p.append(f"<p>Chào {e(greet) if greet else 'thầy/cô'},</p>")
    p.append("<p>Đây là bản góp ý riêng cho buổi onboarding"
             + (f" ngày <b>{e(meta['session_date'])}</b>" if meta.get("session_date") else "")
             + ", để thầy/cô xem lại những phần đã làm tốt và những phần nên ưu tiên ở buổi sau.</p>")

    # Tỷ lệ toàn ca
    cls = scores["classification"]
    color = {"TUAN_THU_TOT": "#1e7b4a", "CHECH_KICH_BAN": "#b26a00"}.get(cls, "#6b6b6b")
    p.append(f'<div style="border:1px solid #ddd;border-left:6px solid {color};padding:12px 16px;margin:12px 0">')
    if cls == "THIEU_DU_LIEU":
        p.append("<div style='font-size:18px'><b>Chưa đủ dữ liệu để tính tỷ lệ tuân thủ toàn ca</b></div>")
        p.append("<div>Lý do: " + e("; ".join(scores["insufficient_reasons"])) + ". Ca này được ghi riêng, không tính là 0%.</div>")
    else:
        p.append(f"<div style='font-size:22px'><b>Tỷ lệ tuân thủ kịch bản: {pct(scores['overall'])}</b></div>")
        p.append(f"<div>Xếp loại: <b>{e(scores['classification_label'])}</b> (ngưỡng tuân thủ tốt: {pct(scores['good_threshold'])})</div>")
    p.append("</div>")
    if result.get("summary_for_mentor"):
        p.append(f"<p>{e(names.humanize(result['summary_for_mentor']))}</p>")

    # 5 hoạt động
    p.append("<h3 style='margin-bottom:6px'>Mức độ thực hiện theo 5 hoạt động</h3>")
    p.append(f"<table style='{_CSS_TABLE}'><tr style='background:#f4f4f4'>"
             f"<th style='{_CSS_TD}'>Hoạt động</th><th style='{_CSS_TD}'>Trọng số</th>"
             f"<th style='{_CSS_TD}'>Thực hiện</th><th style='{_CSS_TD}'>Thời điểm trong video</th></tr>")
    for a in scores["activities"]:
        t = tl.get(a["activity"], {})
        when = f"{t.get('start', '')}–{t.get('end', '')}" if t.get("found") and t.get("start") else ("không thấy trong buổi" if t and not t.get("found") else "")
        cnt = a["counts"]
        detail = ", ".join(f"{STATUS_LABEL[k].lower()} {cnt[k]}" for k in ("FF", "PF", "NF", "NE") if cnt.get(k))
        p.append(f"<tr><td style='{_CSS_TD}'>{e(names.act_name(a['activity']))}</td>"
                 f"<td style='{_CSS_TD}'>{a['weight']}%</td>"
                 f"<td style='{_CSS_TD}'><b>{pct(a['score'])}</b><br><span style='color:#666;font-size:12px'>{e(detail)}</span></td>"
                 f"<td style='{_CSS_TD}'>{e(when)}</td></tr>")
    p.append("</table>")

    # Điểm làm tốt
    strengths = result.get("strengths") or []
    p.append("<h3 style='margin-bottom:6px'>Điều thầy/cô đã làm tốt</h3>")
    if strengths:
        p.append("<ul>")
        for s in strengths[:2]:
            ev = _first_ev(s)
            p.append(f"<li><b>{e(names.step(s.get('criterion_id'), s.get('step_name', '')))}</b>: {e(names.humanize(s.get('description', '')))}"
                     f"<br><span style='color:#555;font-size:13px'>{e(_ev_line(ev))}</span></li>")
        p.append("</ul>")
    else:
        p.append("<p>Chưa đủ bằng chứng trong transcript để nêu điểm làm tốt.</p>")

    # 3 gợi ý
    imps = result.get("improvements") or []
    p.append("<h3 style='margin-bottom:6px'>Ba việc nên ưu tiên ở buổi sau</h3>")
    if not imps:
        p.append("<p>Không có gợi ý ưu tiên.</p>")
    for i, it in enumerate(imps, 1):
        ev = _first_ev(it)
        p.append("<div style='border:1px solid #e3e3e3;padding:10px 14px;margin:8px 0'>")
        p.append(f"<div><b>{i}. {e(names.step(it.get('criterion_id'), it.get('step_name', '')))}</b>"
                 f" <span style='color:#666'>(ưu tiên {e((SEV_LABEL.get(it.get('priority')) or str(it.get('priority') or '')).lower())}"
                 f"{', lúc ' + e(str(ev.get('timestamp'))) if ev.get('timestamp') else ''})</span></div>")
        p.append(f"<div style='color:#555;font-size:13px'>{e(_ev_line(ev))}</div>")
        p.append(f"<div><b>Điều chưa ổn:</b> {e(names.humanize(it.get('problem', '')))}</div>")
        p.append(f"<div><b>Vì sao quan trọng:</b> {e(names.humanize(it.get('logic_impact', '')))}</div>")
        p.append(f"<div><b>Nên làm:</b> {e(names.humanize(it.get('suggestion', '')))}</div>")
        if it.get("suggested_script"):
            p.append(f"<div style='background:#f6f8fa;padding:6px 10px;margin-top:4px'><b>Có thể nói:</b> “{e(it['suggested_script'])}”</div>")
        p.append("</div>")

    # Các phần chệch
    devs = _deviations(result)
    p.append("<h3 style='margin-bottom:6px'>Các phần chệch kịch bản và lý do</h3>")
    if devs:
        p.append(f"<table style='{_CSS_TABLE}'><tr style='background:#f4f4f4'><th style='{_CSS_TD}'>Bước</th>"
                 f"<th style='{_CSS_TD}'>Mức</th><th style='{_CSS_TD}'>Lý do / còn thiếu</th><th style='{_CSS_TD}'>Thời điểm</th></tr>")
        for c in devs:
            miss = "; ".join(c.get("missing_elements") or [])
            why = names.humanize(c.get("rationale", "")) + (f" Còn thiếu: {miss}." if miss else "")
            if c.get("sequence_issue"):
                why += f" Thứ tự: {c['sequence_issue']}"
            p.append(f"<tr><td style='{_CSS_TD}'>{e(names.step(c['id']))}</td>"
                     f"<td style='{_CSS_TD};color:{STATUS_COLOR[c['status']]}'><b>{STATUS_LABEL[c['status']]}</b></td>"
                     f"<td style='{_CSS_TD}'>{e(why)}</td><td style='{_CSS_TD}'>{e(_first_ts(c.get('evidence')))}</td></tr>")
        p.append("</table>")
    else:
        p.append("<p>Không có bước nào bị đánh giá là chưa làm hoặc làm một phần.</p>")

    seq = result.get("sequence") or {}
    seq_devs = [d for d in seq.get("deviations") or [] if d.get("severity") in ("high", "medium")]
    if seq_devs:
        p.append("<h3 style='margin-bottom:6px'>Thứ tự các bước</h3><ul>")
        for d in seq_devs:
            p.append(f"<li><b>{e(SEV_LABEL.get(d.get('severity'), ''))}</b> — {e(names.humanize(d.get('description', '')))}"
                     f" <span style='color:#666'>({e(_first_ts(d.get('evidence')))})</span></li>")
        p.append("</ul>")

    flags = result.get("flags") or []
    if flags:
        p.append("<h3 style='margin-bottom:6px'>Lưu ý về cách dẫn dắt</h3><ul>")
        for f in flags:
            fname = names.flag.get(f.get("id"), {}).get("name", f.get("id"))
            note = f" <i>({SCRIPT_NOTE})</i>" if f.get("script_instructed") else ""
            p.append(f"<li>{e(fname)} — {e(names.humanize(f.get('explanation', '')))} "
                     f"<span style='color:#666'>({e(_first_ts(f.get('evidence')))})</span>{note}</li>")
        p.append("</ul>")

    dq = result.get("data_quality") or {}
    if dq.get("transcript_coverage") in ("partial", "poor"):
        p.append(f"<p style='color:#666;font-size:13px'>Ghi chú dữ liệu: transcript {COVERAGE_LABEL.get(dq['transcript_coverage'])}; "
                 "những bước nằm ở đoạn thiếu được ghi là “không đủ dữ liệu”, không tính vào điểm.</p>")
    if meta.get("detail_url"):
        p.append(f"<p><a href='{e(meta['detail_url'])}'>Xem chi tiết từng tiêu chí và dẫn chứng</a></p>")
    p.append(f"<p style='color:#666;font-size:12px;border-top:1px solid #eee;padding-top:8px'>{e(DISCLAIMER)}</p>")
    p.append("</div>")
    return "\n".join(p)


def mentor_email_text(result: dict, scores: dict, meta: dict, names: Names) -> str:
    L = [f"Chào {meta.get('mentor_name') or 'thầy/cô'},", ""]
    if scores["classification"] == "THIEU_DU_LIEU":
        L.append("Chưa đủ dữ liệu để tính tỷ lệ tuân thủ toàn ca: " + "; ".join(scores["insufficient_reasons"]))
    else:
        L.append(f"Tỷ lệ tuân thủ kịch bản: {pct(scores['overall'])} — {scores['classification_label']}")
    if result.get("summary_for_mentor"):
        L += ["", names.humanize(result["summary_for_mentor"])]
    L += ["", "5 hoạt động:"]
    for a in scores["activities"]:
        L.append(f"- {names.act_name(a['activity'])} ({a['weight']}%): {pct(a['score'])}")
    L += ["", "Điều đã làm tốt:"]
    for s in (result.get("strengths") or [])[:2]:
        L.append(f"- {names.step(s.get('criterion_id'), s.get('step_name', ''))}: {names.humanize(s.get('description', ''))}")
    L += ["", "Ba việc nên ưu tiên:"]
    for i, it in enumerate(result.get("improvements") or [], 1):
        ev = _first_ev(it)
        L.append(f"{i}. {names.step(it.get('criterion_id'), it.get('step_name', ''))} (lúc {ev.get('timestamp', '?')})")
        L.append(f"   Điều chưa ổn: {names.humanize(it.get('problem', ''))}")
        L.append(f"   Nên làm: {names.humanize(it.get('suggestion', ''))}")
        if it.get("suggested_script"):
            L.append(f"   Có thể nói: “{it['suggested_script']}”")
    devs = _deviations(result)
    if devs:
        L += ["", "Các phần chệch kịch bản:"]
        for c in devs:
            L.append(f"- {names.step(c['id'])}: {STATUS_LABEL[c['status']]} ({_first_ts(c.get('evidence'))}) — {names.humanize(c.get('rationale', ''))}")
    if meta.get("detail_url"):
        L += ["", f"Chi tiết: {meta['detail_url']}"]
    L += ["", DISCLAIMER]
    return "\n".join(L)


def mentor_eml(result: dict, scores: dict, meta: dict, names: Names) -> bytes:
    msg = EmailMessage()
    msg["Subject"] = subject(meta, scores)
    if meta.get("mentor_email"):
        msg["To"] = meta["mentor_email"]
    msg["X-Unsent"] = "1"  # mở ra là bản nháp, người gửi kiểm rồi mới gửi
    msg.set_content(mentor_email_text(result, scores, meta, names))
    msg.add_alternative(mentor_email_html(result, scores, meta, names), subtype="html")
    return bytes(msg)


# ------------------------------------------------------------------ trang chi tiết (kiểm định nội bộ)

def detail_html(result: dict, scores: dict, meta: dict, names: Names, run_info: dict) -> str:
    p = ["<!doctype html><html lang='vi'><head><meta charset='utf-8'>"
         "<meta name='viewport' content='width=device-width,initial-scale=1'>"
         f"<title>Chi tiết chấm onboarding {e(meta.get('case_id', ''))}</title>"
         "<style>body{font-family:Arial,Helvetica,sans-serif;margin:16px;color:#1f1f1f;background:#fff}"
         "table{border-collapse:collapse;width:100%;font-size:13px}td,th{border:1px solid #ddd;padding:5px 7px;vertical-align:top}"
         "th{background:#f4f4f4}.ok{color:#1e7b4a}.bad{color:#b3261e}.muted{color:#666}h2{margin-top:28px}"
         ".warn{background:#fff4e5;padding:8px 12px;border:1px solid #f0c36d}</style></head><body>"]
    p.append(f"<h1>Chi tiết chấm onboarding — {e(meta.get('case_id', ''))}</h1>")
    p.append("<p class='warn'>Nội bộ — có trích lời thoại của gia đình. Chỉ người có quyền kiểm định được xem.</p>")
    p.append(f"<p>Ngày buổi: {e(meta.get('session_date') or '—')} · Tỷ lệ tuân thủ: <b>{pct(scores['overall'])}</b> · "
             f"Xếp loại: <b>{e(scores['classification_label'])}</b> · Tiêu chí không đủ bằng chứng: {scores['ne_ratio']:.0%} · "
             f"Thứ tự: {e(SEQ_LABEL.get((result.get('sequence') or {}).get('status'), ''))}</p>")
    dq = result.get("data_quality") or {}
    p.append("<h2>Chất lượng dữ liệu</h2><ul>"
             f"<li>Độ phủ: {e(COVERAGE_LABEL.get(dq.get('transcript_coverage'), str(dq.get('transcript_coverage'))))}</li>"
             f"<li>Độ chắc gán vai: {e(str(dq.get('speaker_confidence')))}</li>"
             "<li>Gán vai: " + e("; ".join(f"{m.get('label')} → {m.get('role')}" for m in dq.get("speaker_mapping") or [])) + "</li>")
    for it in dq.get("issues") or []:
        p.append(f"<li>{e(it)}</li>")
    p.append("</ul>")

    p.append("<h2>37 tiêu chí</h2><table><tr><th>Mã</th><th>Hoạt động</th><th>Bước</th><th>Trạng thái</th>"
             "<th>Lý do</th><th>Còn thiếu</th><th>Bằng chứng</th></tr>")
    for c in result["criteria"]:
        st = c["status"]
        changed = f"<br><span class='bad'>model: {e(c['status_model'])} → hạ vì {e(c.get('downgraded', ''))}</span>" if c.get("status_model") else ""
        evs = "<br>".join(
            f"<span class='{'ok' if ev.get('verified') else 'bad'}'>{'✓' if ev.get('verified') else '✗'}</span> {e(_ev_line(ev))}"
            + (" <span class='muted'>(đã sửa mốc giờ)</span>" if ev.get("timestamp_corrected") else "")
            for ev in (c.get("evidence") or []) + (c.get("evidence_unverified") or []))
        runs = c.get("run_statuses") or []
        votes = (f"<br><span class='{'bad' if len(set(runs)) > 1 else 'muted'}'>các lần chấm: {e(' / '.join(runs))}</span>"
                 if len(runs) > 1 else "")
        p.append(f"<tr><td>{c['id']}</td><td>{names.act_of(c['id'])}</td><td>{e(names.step(c['id']))}</td>"
                 f"<td style='color:{STATUS_COLOR[st]}'><b>{STATUS_LABEL[st]}</b>{changed}{votes}</td>"
                 f"<td>{e(c.get('rationale', ''))}{'<br><i>Thứ tự: ' + e(c['sequence_issue']) + '</i>' if c.get('sequence_issue') else ''}</td>"
                 f"<td>{e('; '.join(c.get('missing_elements') or []))}</td><td>{evs}</td></tr>")
    p.append("</table>")

    p.append("<h2>6 logic liên kết</h2><table><tr><th>Mã</th><th>Liên kết</th><th>Kết quả</th><th>Lý do</th><th>Bằng chứng</th></tr>")
    for lk in result["links"]:
        evs = "<br>".join(e(_ev_line(ev)) for ev in lk.get("evidence") or [])
        p.append(f"<tr><td>{lk['id']}</td><td>{e(names.link.get(lk['id'], {}).get('name', ''))}</td>"
                 f"<td><b>{e(LINK_LABEL.get(lk['status'], lk['status']))}</b></td><td>{e(lk.get('rationale', ''))}</td><td>{evs}</td></tr>")
    p.append("</table>")

    seq = result.get("sequence") or {}
    p.append(f"<h2>Thứ tự — {e(SEQ_LABEL.get(seq.get('status'), ''))}</h2>"
             f"<p>Thứ tự hoạt động quan sát được: {e(' → '.join(str(x) for x in seq.get('observed_activity_order') or []))}</p><ul>")
    for d in seq.get("deviations") or []:
        p.append(f"<li><b>{e(d.get('rule_id', ''))}</b> ({e(SEV_LABEL.get(d.get('severity'), ''))}): {e(d.get('description', ''))} "
                 f"— ảnh hưởng {e(', '.join(d.get('affected_criteria') or []))} · {e(_first_ts(d.get('evidence')))}</li>")
    p.append("</ul>")

    p.append("<h2>Cờ hành vi</h2><ul>")
    for f in result.get("flags") or []:
        p.append(f"<li><b>{e(f.get('id', ''))}</b> {e(names.flag.get(f.get('id'), {}).get('name', ''))} — mức {e(SEV_LABEL.get(f.get('severity'), ''))}"
                 f"{' · <i>theo kịch bản</i>' if f.get('script_instructed') else ''}: {e(f.get('explanation', ''))} "
                 f"<span class='muted'>{e(' | '.join(_ev_line(ev) for ev in f.get('evidence') or []))}</span></li>")
    p.append("</ul>")

    unver = [("Cờ", result.get("flags_unverified")), ("Điểm tốt", result.get("strengths_unverified")),
             ("Gợi ý", result.get("improvements_unverified"))]
    issues = run_info.get("ai_issues") or []
    p.append("<h2>Lỗi của AI (phục vụ nghiệm thu)</h2><ul>")
    for it in issues:
        p.append(f"<li>{e(it)}</li>")
    n_runs = (run_info.get("stability") or {}).get("runs", 1)
    for label, items in unver:
        for it in items or []:
            code = e(it.get("id") or it.get("criterion_id") or "")
            if it.get("minority_only"):
                p.append(f"<li>{label} {code} chỉ có ở {it.get('runs')}/{n_runs} lần chấm → không giữ</li>")
            else:
                p.append(f"<li>{label} bị loại vì trích dẫn không có trong transcript: {code}"
                         + (f" ({it.get('runs')} lần chấm)" if it.get("runs") else "") + "</li>")
    if not issues and not any(items for _, items in unver):
        p.append("<li>Không có.</li>")
    p.append("</ul>")
    qs = run_info.get("quote_stats") or {}
    usage = run_info.get("usage") or {}
    stab = run_info.get("stability") or {}
    if stab.get("runs", 1) > 1:
        unstable = ", ".join(f"{cid} {names.step(cid)}" for cid in stab.get("unstable_criteria") or [])
        p.append(f"<h2>Độ ổn định ({stab['runs']} lần chấm, lấy đa số)</h2><ul>"
                 f"<li>Tiêu chí mọi lần chấm giống nhau: {stab.get('criteria_all_agree', 0):.0%} · "
                 f"trùng trung bình giữa 2 lần: {stab.get('pairwise_agreement_mean', 0):.0%}</li>"
                 f"<li>Tiêu chí các lần chấm khác nhau (nên người kiểm định xem lại): {e(unstable) or 'không có'}</li>"
                 + (f"<li class='bad'>Lần gọi lỗi: {e('; '.join(run_info.get('run_errors') or []))}</li>" if run_info.get("run_errors") else "")
                 + "</ul>")
    p.append("<h2>Thông tin chạy</h2><ul>"
             f"<li>Model: {e(str(run_info.get('model')))} ({e(str(run_info.get('model_version')))}) · thời gian {e(str(run_info.get('latency_sec')))} giây</li>"
             f"<li>Token: prompt {usage.get('prompt_tokens')} · output {usage.get('output_tokens')} · thinking {usage.get('thinking_tokens')} · "
             f"chi phí ước {run_info.get('cost_usd_est')} USD</li>"
             f"<li>Trích dẫn (cộng {n_runs} lần chấm): {qs.get('total', 0)} · khớp nguyên văn {qs.get('exact', 0)} · "
             f"gần đúng {qs.get('fuzzy', 0)} · không thấy {qs.get('not_found', 0)} · quá ngắn {qs.get('too_short', 0)}</li>"
             f"<li>Transcript: {e(str(run_info.get('transcript_format')))} · {run_info.get('segments')} đoạn · {run_info.get('words')} từ</li>"
             "</ul></body></html>")
    return "\n".join(p)
