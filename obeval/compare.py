"""Giai đoạn 1 — bảng đối chiếu AI với người chấm (chỉ tiêu nghiệm thu v3.0).

Người chấm điền CSV từ `human-template` (cột: ma, ten_buoc, hoat_dong, trang_thai, ghi_chu).
Cũng đọc được `answer_key.json` của bộ dữ liệu giả (có `accept` = trạng thái chấp nhận thêm).
"""
from __future__ import annotations

import csv
import unicodedata
import json
from pathlib import Path

from .score import compute, pct
from .validate import CRIT_STATUSES, LINK_STATUSES, LK_IDS, OB_IDS

TARGETS = {"criteria_agreement": 0.85, "overall_diff_pp": 5.0, "error_recall": 0.85, "link_agreement": 0.80}


def write_template(path: Path, criteria_doc: dict) -> None:
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["ma", "ten_buoc", "hoat_dong", "trang_thai", "ghi_chu"])
        for c in criteria_doc["criteria"]:
            w.writerow([c["id"], c["name"], c["activity"], "", ""])
        for lk in criteria_doc["links"]:
            w.writerow([lk["id"], lk["name"], "", "", ""])
        for fl in criteria_doc["flags"]:
            w.writerow([fl["id"], fl["name"], "", "", "ghi 'co' nếu buổi có hành vi này"])
        w.writerow(["GHI_CHU", "Tiêu chí: FF/PF/NF/NA/NE · Liên kết: DAT/DAT_MOT_PHAN/CHUA_DAT/KHONG_DU_DU_LIEU · Cờ: co hoặc để trống", "", "", ""])


def load_human(path: Path) -> dict:
    """→ {'criteria': {OB: [trạng thái chấp nhận...]}, 'links': {LK: [...]}, 'flags': set|None}"""
    path = Path(path)
    if path.suffix.lower() == ".json":
        d = json.loads(path.read_text(encoding="utf-8"))
        crit = {}
        for cid, v in (d.get("criteria") or {}).items():
            acc = [v["expected"]]
            extra = v.get("accept")
            for a in ([extra] if isinstance(extra, str) else (extra or [])):
                if a not in acc:
                    acc.append(a)
            crit[cid.upper()] = acc
        links = {k.upper(): [v if isinstance(v, str) else v.get("expected")] for k, v in (d.get("links") or {}).items()}
        flags = {f["id"] for f in d.get("flags") or []}
        return {"criteria": crit, "links": links, "flags": flags}
    crit, links, flags, has_flag_col, bad = {}, {}, set(), False, []
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "cp1258", "cp1252"):  # Excel có thể lưu CSV kiểu ANSI
        try:
            text = unicodedata.normalize("NFC", raw.decode(enc))  # cp1258 lưu dấu thanh dạng tổ hợp
            break
        except UnicodeDecodeError:
            continue
    try:  # Excel tiếng Việt lưu CSV bằng ";"
        dialect = csv.Sniffer().sniff(text.split("\n", 1)[0], delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    for row in csv.DictReader(text.splitlines(), dialect=dialect):
        row = {(k or "").strip().lower(): v for k, v in row.items()}
        ma = (row.get("ma") or "").strip().upper()
        raw_val = (row.get("trang_thai") or "").strip()
        aliases = _LINK_ALIASES if ma in LK_IDS else _HUMAN_ALIASES
        val = aliases.get(raw_val.upper(), raw_val.upper())
        if ma in OB_IDS and val:
            if val in CRIT_STATUSES:
                crit[ma] = [val]
            else:
                bad.append(f"{ma}={raw_val!r}")
        elif ma in LK_IDS and val:
            if val in LINK_STATUSES:
                links[ma] = [val]
            else:
                bad.append(f"{ma}={raw_val!r}")
        elif ma.startswith("F") and len(ma) == 3:
            has_flag_col = True
            if val in ("CO", "CÓ", "X", "1", "YES"):
                flags.add(ma)
    if bad:
        raise ValueError(f"{path.name}: giá trị không hợp lệ {', '.join(bad)} — tiêu chí dùng FF/PF/NF/NA/NE, "
                         "liên kết dùng DAT/DAT_MOT_PHAN/CHUA_DAT/KHONG_DU_DU_LIEU")
    if not crit:
        raise ValueError(f"{path.name}: không đọc được tiêu chí nào (kiểm cột 'ma', 'trang_thai' và dấu phân cách)")
    return {"criteria": crit, "links": links, "flags": flags if has_flag_col else None}


_HUMAN_ALIASES = {
    "LÀM ĐỦ": "FF", "FULLY": "FF", "FULLY FOLLOWED": "FF",
    "LÀM MỘT PHẦN": "PF", "PARTIALLY": "PF", "PARTIALLY FOLLOWED": "PF",
    "CHƯA LÀM": "NF", "NOT FOLLOWED": "NF",
    "KHÔNG ÁP DỤNG": "NA", "N/A": "NA",
    "KHÔNG ĐỦ DỮ LIỆU": "NE", "INSUFFICIENT EVIDENCE": "NE",
}
_LINK_ALIASES = {
    "ĐẠT": "DAT", "ĐẠT MỘT PHẦN": "DAT_MOT_PHAN", "CHƯA ĐẠT": "CHUA_DAT",
    "KHÔNG ĐỦ DỮ LIỆU": "KHONG_DU_DU_LIEU", "NE": "KHONG_DU_DU_LIEU",
}


def compare(ai: dict, human: dict, criteria_doc: dict) -> dict:
    """ai = result.json đã qua kiểm (có 'criteria', 'links', 'flags', 'scores')."""
    ai_c = {c["id"]: c for c in ai["criteria"]}
    rows, strict, lenient, n = [], 0, 0, 0
    err_h = err_hit = err_ai = err_ai_hit = 0
    for cid in OB_IDS:
        hs = human["criteria"].get(cid)
        a = ai_c[cid]["status"]
        if not hs:
            continue
        n += 1
        s_ok = a == hs[0]
        l_ok = a in hs
        strict += s_ok
        lenient += l_ok
        if hs[0] in ("NF", "PF"):
            err_h += 1
            err_hit += a in ("NF", "PF")
        if a in ("NF", "PF"):
            err_ai += 1
            err_ai_hit += hs[0] in ("NF", "PF") or any(h in ("NF", "PF") for h in hs)
        rows.append({"id": cid, "human": "/".join(hs), "ai": a, "match": s_ok, "match_lenient": l_ok})

    l_rows, l_ok_n, l_n = [], 0, 0
    ai_l = {lk["id"]: lk["status"] for lk in ai["links"]}
    for lid in LK_IDS:
        hs = human["links"].get(lid)
        if not hs or not hs[0]:
            continue
        l_n += 1
        ok = ai_l.get(lid) in hs
        l_ok_n += ok
        l_rows.append({"id": lid, "human": hs[0], "ai": ai_l.get(lid), "match": ok})

    # Điểm toàn ca của người chấm: tính cùng công thức từ trạng thái người chấm.
    pseudo = {"criteria": [{"id": cid, "status": (human["criteria"].get(cid) or ["NE"])[0]} for cid in OB_IDS],
              "data_quality": {}}
    h_overall = compute(pseudo, criteria_doc)["overall"]
    a_overall = ai["scores"]["overall"]
    diff_pp = None if h_overall is None or a_overall is None else abs(h_overall - a_overall) * 100

    flags = None
    if human.get("flags") is not None:
        ai_f = {f.get("id") for f in ai.get("flags") or []}
        hf = human["flags"]
        flags = {"human": sorted(hf), "ai": sorted(ai_f),
                 "recall": (len(hf & ai_f) / len(hf)) if hf else None,
                 "precision": (len(hf & ai_f) / len(ai_f)) if ai_f else None}

    important = [c for c in ai["criteria"] if c["status"] == "NF"]
    with_ev = [c for c in important if any(ev.get("verified") for ev in c.get("evidence") or [])]
    m = {
        "criteria_n": n,
        "criteria_agreement": strict / n if n else None,
        "criteria_agreement_lenient": lenient / n if n else None,
        "overall_ai": a_overall, "overall_human": h_overall, "overall_diff_pp": diff_pp,
        "error_recall": err_hit / err_h if err_h else None,
        "error_precision": err_ai_hit / err_ai if err_ai else None,
        "link_agreement": l_ok_n / l_n if l_n else None,
        "flags": flags,
        "nf_with_verified_evidence": (len(with_ev) / len(important)) if important else None,
    }
    m["pass"] = {
        "criteria_agreement": m["criteria_agreement"] is not None and m["criteria_agreement"] >= TARGETS["criteria_agreement"],
        "overall_diff": diff_pp is not None and diff_pp <= TARGETS["overall_diff_pp"],
        "error_recall": m["error_recall"] is not None and m["error_recall"] >= TARGETS["error_recall"],
        "link_agreement": m["link_agreement"] is not None and m["link_agreement"] >= TARGETS["link_agreement"],
        "evidence_100": m["nf_with_verified_evidence"] in (None, 1.0),
    }
    return {"metrics": m, "criteria_rows": rows, "link_rows": l_rows}


def _f(x, kind="pct"):
    if x is None:
        return "—"
    return pct(x) if kind == "pct" else f"{x:.1f}"


def to_markdown(case: str, cmp: dict, names) -> str:
    m = cmp["metrics"]
    ok = lambda b: "ĐẠT" if b else "CHƯA"  # noqa: E731
    L = [f"## Ca {case}", "",
         "| Chỉ tiêu | Kết quả | Mục tiêu | |", "|---|---|---|---|",
         f"| Phân loại tiêu chí trùng người chấm | {_f(m['criteria_agreement'])} (chấp nhận thêm: {_f(m['criteria_agreement_lenient'])}) | ≥ 85% | {ok(m['pass']['criteria_agreement'])} |",
         f"| Lệch tỷ lệ tuân thủ toàn ca | AI {_f(m['overall_ai'])} · người {_f(m['overall_human'])} · lệch {_f(m['overall_diff_pp'], 'num')} điểm % | ≤ 5 | {ok(m['pass']['overall_diff'])} |",
         f"| Tìm đúng lỗi (NF/PF của người chấm) | {_f(m['error_recall'])} · độ chính xác {_f(m['error_precision'])} | ≥ 85% | {ok(m['pass']['error_recall'])} |",
         f"| Logic liên kết trùng | {_f(m['link_agreement'])} | ≥ 80% | {ok(m['pass']['link_agreement'])} |",
         f"| Tiêu chí NF có dẫn chứng đã xác minh | {_f(m['nf_with_verified_evidence'])} | 100% | {ok(m['pass']['evidence_100'])} |"]
    if m["flags"]:
        L.append(f"| Cờ hành vi | recall {_f(m['flags']['recall'])} · precision {_f(m['flags']['precision'])} | — | |")
    L += ["", "| Mã | Bước | Người chấm | AI | Trùng |", "|---|---|---|---|---|"]
    for r in cmp["criteria_rows"]:
        L.append(f"| {r['id']} | {names.step(r['id'])} | {r['human']} | {r['ai']} | {'✓' if r['match'] else ('≈' if r['match_lenient'] else '✗')} |")
    for r in cmp["link_rows"]:
        L.append(f"| {r['id']} | {names.link.get(r['id'], {}).get('name', '')} | {r['human']} | {r['ai']} | {'✓' if r['match'] else '✗'} |")
    return "\n".join(L)
