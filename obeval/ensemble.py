"""Gộp nhiều lần chấm của cùng một ca (self-consistency) — giảm dao động FF↔PF giữa các lần chạy.

Đo 09/10 trên ca giả: 2 lần chạy Gemini 2.5 Pro (temperature 0) cho độ trùng đáp án 89% và 76%.
Mỗi lần chạy đã qua validate + verify (trích dẫn bịa → NE) TRƯỚC khi gộp.

Luật gộp:
- tiêu chí: đa số tuyệt đối; không có đa số → trung vị trên thang NF < PF < FF (NA/NE không tính);
  ít hơn 2 lần có trạng thái chấm được → NE. Không chắc thì về mức thấp hơn (trung vị lấy phần dưới).
- liên kết: như trên với CHUA_DAT < DAT_MOT_PHAN < DAT.
- cờ / lệch thứ tự: giữ khi xuất hiện ở > nửa số lần chạy.
- phần chữ (điểm tốt, gợi ý, tóm tắt, chất lượng dữ liệu, mốc hoạt động): lấy từ lần chạy gần kết quả gộp nhất.
"""
from __future__ import annotations

import copy
from collections import Counter

CRIT_ORDER = {"NF": 0, "PF": 1, "FF": 2}
LINK_ORDER = {"CHUA_DAT": 0, "DAT_MOT_PHAN": 1, "DAT": 2}
SEQ_ORDER = {"LECH_NGHIEM_TRONG": 0, "LECH_NHE": 1, "DUNG_THU_TU": 2}


def _vote(values: list[str], order: dict[str, int], fallback: str) -> str:
    n = len(values)
    top, cnt = Counter(values).most_common(1)[0]
    if cnt * 2 > n:
        return top
    scored = sorted((v for v in values if v in order), key=order.get)
    if not scored:
        return fallback
    return scored[(len(scored) - 1) // 2]  # trung vị, lệch về mức thấp hơn khi số chẵn ([FF, NA] → FF)


def reconcile_text(rep: dict, results: list[dict]) -> dict:
    """Điểm tốt chỉ cho tiêu chí FF; gợi ý chỉ cho tiêu chí PF/NF — theo trạng thái CUỐI (sau gộp/hạ NE).

    Lấy từ lần chạy đại diện trước, thiếu thì bổ sung từ các lần khác; không trùng tiêu chí.
    """
    status = {c["id"]: c["status"] for c in rep["criteria"]}

    def _pick(key, extra_key, ok_status, limit):
        out, seen = [], set()
        for r in [rep] + [x for x in results if x is not rep]:
            for it in (r.get(key) or []) + (r.get(extra_key) or [] if extra_key else []):
                cid = it.get("criterion_id")
                if cid in seen or status.get(cid) not in ok_status:
                    continue
                seen.add(cid)
                out.append(it)
        return out[:limit]

    rep["strengths"] = _pick("strengths", None, ("FF",), 3)
    rep["improvements"] = _pick("improvements", "improvements_extra", ("PF", "NF"), 3)
    return rep


def aggregate(results: list[dict]) -> tuple[dict, dict]:
    """results: các kết quả đã normalize + verify (cùng thứ tự OB/LK). Trả (kết quả gộp, độ ổn định)."""
    n = len(results)
    if n == 1:
        return reconcile_text(results[0], results), {"runs": 1}
    crit_ids = [c["id"] for c in results[0]["criteria"]]
    merged_crit, unstable = [], []
    for i, cid in enumerate(crit_ids):
        statuses = [r["criteria"][i]["status"] for r in results]
        chosen = _vote(statuses, CRIT_ORDER, "NE")
        src = next(r["criteria"][i] for r in results if r["criteria"][i]["status"] == chosen) \
            if chosen in statuses else {**results[0]["criteria"][i], "status": chosen, "evidence": [], "rationale": "Các lần chấm không thống nhất."}
        item = copy.deepcopy(src)
        item["run_statuses"] = statuses
        if len(set(statuses)) > 1:
            unstable.append(cid)
        merged_crit.append(item)

    merged_links = []
    for i in range(len(results[0]["links"])):
        statuses = [r["links"][i]["status"] for r in results]
        chosen = _vote(statuses, LINK_ORDER, "KHONG_DU_DU_LIEU")
        src = next((r["links"][i] for r in results if r["links"][i]["status"] == chosen), results[0]["links"][i])
        item = copy.deepcopy(src)
        item["status"] = chosen
        item["run_statuses"] = statuses
        merged_links.append(item)

    flag_runs = Counter(fid for r in results for fid in {f["id"] for f in r.get("flags") or []})
    merged_flags = []
    for fid, cnt in flag_runs.items():
        if cnt * 2 > n:
            src = next(f for r in results for f in r.get("flags") or [] if f["id"] == fid)
            merged_flags.append({**copy.deepcopy(src), "runs_flagged": cnt})
    merged_flags.sort(key=lambda f: f["id"])

    seq_status = _vote([(r.get("sequence") or {}).get("status", "KHONG_DU_DU_LIEU") for r in results], SEQ_ORDER, "KHONG_DU_DU_LIEU")

    def _dev_key(d):
        return d.get("rule_id") or d.get("description") or ""

    dev_runs = Counter(k for r in results for k in {_dev_key(d) for d in (r.get("sequence") or {}).get("deviations") or []})
    merged_devs = []
    for key, cnt in dev_runs.items():
        if key and cnt * 2 > n:
            src = next(d for r in results for d in (r.get("sequence") or {}).get("deviations") or [] if _dev_key(d) == key)
            merged_devs.append({**copy.deepcopy(src), "runs_found": cnt})

    # Lần chạy "đại diện": trùng kết quả gộp nhiều nhất → lấy phần chữ của nó.
    chosen_status = [c["status"] for c in merged_crit]
    best = max(range(n), key=lambda k: sum(a == b for a, b in zip([c["status"] for c in results[k]["criteria"]], chosen_status)))
    rep = copy.deepcopy(results[best])
    rep["criteria"] = merged_crit
    rep["links"] = merged_links
    rep["flags"] = merged_flags
    rep["sequence"] = {**(rep.get("sequence") or {}), "status": seq_status, "deviations": merged_devs}
    # "Thiếu dữ liệu" theo đa số (hoà → coi là thiếu: ca được tính riêng, không bị chấm 0%).
    insuff = sum(bool((r.get("data_quality") or {}).get("insufficient_data")) for r in results)
    rep.setdefault("data_quality", {})["insufficient_data"] = insuff * 2 >= n
    rep["data_quality"]["insufficient_data_runs"] = insuff
    kept_flags = {f["id"] for f in merged_flags}
    unver: dict[str, dict] = {}
    for r in results:
        for f in r.get("flags_unverified") or []:
            if f.get("id") not in kept_flags:
                unver.setdefault(f.get("id"), {**f, "runs": 0})["runs"] += 1
    for fid, cnt in flag_runs.items():  # cờ chỉ có ở thiểu số lần chấm: ghi lại để người kiểm định biết
        if fid not in kept_flags and fid not in unver:
            unver[fid] = {"id": fid, "runs": cnt, "minority_only": True}
    rep["flags_unverified"] = list(unver.values())
    reconcile_text(rep, results)

    pair_agree = []
    for a in range(n):
        for b in range(a + 1, n):
            same = sum(x["status"] == y["status"] for x, y in zip(results[a]["criteria"], results[b]["criteria"]))
            pair_agree.append(same / len(crit_ids))
    stability = {
        "runs": n,
        "representative_run": best,
        "criteria_all_agree": 1 - len(unstable) / len(crit_ids),
        "pairwise_agreement_mean": sum(pair_agree) / len(pair_agree),
        "unstable_criteria": unstable,
    }
    return rep, stability
