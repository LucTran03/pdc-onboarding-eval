"""Tính điểm bằng code (model không tự tính): FF=1, PF=0,5, NF=0; NA/NE loại khỏi mẫu số."""
from __future__ import annotations

from collections import Counter

from . import config

VALUE = {"FF": 1.0, "PF": 0.5, "NF": 0.0}

CLASS_GOOD = "TUAN_THU_TOT"
CLASS_DEVIATE = "CHECH_KICH_BAN"
CLASS_INSUFFICIENT = "THIEU_DU_LIEU"

CLASS_LABEL = {
    CLASS_GOOD: "Tuân thủ tốt",
    CLASS_DEVIATE: "Chệch kịch bản",
    CLASS_INSUFFICIENT: "Thiếu dữ liệu",
}


def compute(result: dict, criteria_doc: dict, good_threshold: float = config.GOOD_THRESHOLD,
            ne_ratio_limit: float = config.NE_RATIO_INSUFFICIENT) -> dict:
    act_of = {c["id"]: c["activity"] for c in criteria_doc["criteria"]}
    weights = {a["id"]: a["weight"] for a in criteria_doc["activities"]}
    per_act: dict[int, list[float]] = {a: [] for a in weights}
    counts_by_act: dict[int, Counter] = {a: Counter() for a in weights}
    counts = Counter()
    for c in result["criteria"]:
        st = c["status"]
        counts[st] += 1
        a = act_of[c["id"]]
        counts_by_act[a][st] += 1
        if st in VALUE:
            per_act[a].append(VALUE[st])

    activities = []
    num = den = 0.0
    for a, w in weights.items():
        vals = per_act[a]
        sc = sum(vals) / len(vals) if vals else None
        if sc is not None:
            num += w * sc
            den += w
        activities.append({"activity": a, "weight": w, "score": sc, "counts": dict(counts_by_act[a])})
    overall = num / den if den else None

    n = len(result["criteria"])
    ne_ratio = counts["NE"] / n if n else 1.0
    insufficient = bool(result.get("data_quality", {}).get("insufficient_data")) or ne_ratio > ne_ratio_limit or overall is None
    if insufficient:
        cls = CLASS_INSUFFICIENT
    elif overall >= good_threshold:
        cls = CLASS_GOOD
    else:
        cls = CLASS_DEVIATE
    return {
        "overall": overall,
        "activities": activities,
        "counts": dict(counts),
        "ne_ratio": ne_ratio,
        "classification": cls,
        "classification_label": CLASS_LABEL[cls],
        "good_threshold": good_threshold,
        "ne_ratio_limit": ne_ratio_limit,
        "insufficient_reasons": [r for r, ok in (
            ("model báo transcript không đủ để chấm", result.get("data_quality", {}).get("insufficient_data")),
            (f"tỷ lệ tiêu chí không đủ bằng chứng {ne_ratio:.0%} > {ne_ratio_limit:.0%}", ne_ratio > ne_ratio_limit),
            ("không có tiêu chí nào chấm được", overall is None),
        ) if ok],
    }


def pct(x: float | None) -> str:
    return "—" if x is None else f"{x * 100:.0f}%"
