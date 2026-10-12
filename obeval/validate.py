"""Kiểm JSON model trả về theo schema đầy đủ, rồi vá chỗ thiếu một cách an toàn (về NE, không bịa)."""
from __future__ import annotations

import copy

OB_IDS = [f"OB{i:02d}" for i in range(1, 38)]
LK_IDS = [f"LK{i:02d}" for i in range(1, 7)]
FLAG_IDS = [f"F{i:02d}" for i in range(1, 11)]
SEVERITIES = ("high", "medium", "low")
CRIT_STATUSES = {"FF", "PF", "NF", "NA", "NE"}
LINK_STATUSES = {"DAT", "DAT_MOT_PHAN", "CHUA_DAT", "KHONG_DU_DU_LIEU"}


def schema_errors(data: dict, schema: dict) -> list[str]:
    try:
        import jsonschema
    except ImportError:  # gói thiếu thì chỉ dựa vào bước vá bên dưới
        return ["(bỏ qua kiểm schema: thiếu gói jsonschema)"]
    validator = jsonschema.Draft202012Validator(schema)
    out = []
    for err in sorted(validator.iter_errors(data), key=lambda e: list(e.absolute_path)):
        path = "/".join(str(p) for p in err.absolute_path) or "(gốc)"
        out.append(f"{path}: {err.message[:200]}")
    return out


def normalize(data: dict) -> tuple[dict, list[str]]:
    """Trả (bản đã vá, danh sách lỗi của AI). Không đổi nhận định hợp lệ của model."""
    d = copy.deepcopy(data) if isinstance(data, dict) else {}
    issues: list[str] = []

    dq = d.get("data_quality") if isinstance(d.get("data_quality"), dict) else {}
    d["data_quality"] = dq
    # Giá trị ngoài enum → mặc định (chữ tự do của model không được lọt vào bảng điều khiển).
    if dq.get("transcript_coverage") not in ("full", "partial", "poor"):
        dq["transcript_coverage"] = "partial"
    if dq.get("speaker_confidence") not in ("high", "medium", "low"):
        dq["speaker_confidence"] = "low"
    dq.setdefault("speaker_mapping", [])
    dq.setdefault("issues", [])
    dq["insufficient_data"] = bool(dq.get("insufficient_data"))

    # Tiêu chí: mỗi mã đúng một lần; thiếu → NE; trạng thái lạ → NE.
    seen: dict[str, dict] = {}
    for c in d.get("criteria") or []:
        cid = str(c.get("id", "")).upper().strip()
        if cid not in OB_IDS:
            issues.append(f"Bỏ tiêu chí mã lạ: {cid!r}")
            continue
        if cid in seen:
            issues.append(f"{cid} trả về 2 lần — giữ lần đầu")
            continue
        c["id"] = cid
        if c.get("status") not in CRIT_STATUSES:
            issues.append(f"{cid}: trạng thái {c.get('status')!r} không hợp lệ → NE")
            c["status"] = "NE"
        c.setdefault("rationale", "")
        c.setdefault("evidence", [])
        c.setdefault("missing_elements", [])
        seen[cid] = c
    for cid in OB_IDS:
        if cid not in seen:
            issues.append(f"{cid}: model không trả về → NE")
            seen[cid] = {"id": cid, "status": "NE", "rationale": "AI không trả về tiêu chí này.",
                         "evidence": [], "missing_elements": [], "ai_missing": True}
    d["criteria"] = [seen[cid] for cid in OB_IDS]

    lseen: dict[str, dict] = {}
    for lk in d.get("links") or []:
        lid = str(lk.get("id", "")).upper().strip()
        if lid not in LK_IDS or lid in lseen:
            issues.append(f"Bỏ logic liên kết trùng/lạ: {lid!r}")
            continue
        lk["id"] = lid
        if lk.get("status") not in LINK_STATUSES:
            issues.append(f"{lid}: trạng thái {lk.get('status')!r} không hợp lệ → KHONG_DU_DU_LIEU")
            lk["status"] = "KHONG_DU_DU_LIEU"
        lk.setdefault("rationale", "")
        lk.setdefault("evidence", [])
        lseen[lid] = lk
    for lid in LK_IDS:
        if lid not in lseen:
            issues.append(f"{lid}: model không trả về → KHONG_DU_DU_LIEU")
            lseen[lid] = {"id": lid, "status": "KHONG_DU_DU_LIEU", "rationale": "AI không trả về.",
                          "evidence": [], "ai_missing": True}
    d["links"] = [lseen[lid] for lid in LK_IDS]

    flags = []
    for f in d.get("flags") or []:
        fid = str(f.get("id", "")).upper().strip()
        if fid not in FLAG_IDS:
            issues.append(f"Bỏ cờ mã lạ: {fid!r}")
            continue
        f["id"] = fid
        f.setdefault("evidence", [])
        f["script_instructed"] = bool(f.get("script_instructed"))
        if f.get("severity") not in SEVERITIES:
            f["severity"] = "medium"
        flags.append(f)
    d["flags"] = flags
    for key in ("strengths", "improvements"):
        items = []
        for it in d.get(key) or []:
            if not isinstance(it, dict):
                continue
            cid = str(it.get("criterion_id", "")).upper().strip()
            it["criterion_id"] = cid
            if cid not in OB_IDS:
                issues.append(f"{key}: criterion_id {cid!r} không phải mã OB")
            if key == "improvements" and it.get("priority") not in SEVERITIES:
                it["priority"] = "medium"
            it.setdefault("evidence", [])
            items.append(it)
        d[key] = items  # cắt còn 3 gợi ý SAU khi kiểm trích dẫn (verify.py)
    d.setdefault("activities_timeline", [])
    seq = d.get("sequence") if isinstance(d.get("sequence"), dict) else {}
    d["sequence"] = seq
    if seq.get("status") not in ("DUNG_THU_TU", "LECH_NHE", "LECH_NGHIEM_TRONG", "KHONG_DU_DU_LIEU"):
        seq["status"] = "KHONG_DU_DU_LIEU"
    seq.setdefault("observed_activity_order", [])
    seq.setdefault("deviations", [])
    d.setdefault("summary_for_mentor", "")
    return d, issues
