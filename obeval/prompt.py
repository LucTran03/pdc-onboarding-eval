"""Ghép system instruction + nội dung gửi model; làm sạch schema cho Vertex."""
from __future__ import annotations

import copy
import json
import re
from pathlib import Path

from . import config
from .transcript import Transcript, fmt_time, gaps, render, speaker_stats


def load_system_prompt(path: Path = config.SYSTEM_PROMPT_PATH) -> str:
    text = path.read_text(encoding="utf-8")
    return re.sub(r"<!--.*?-->", "", text, flags=re.S).strip()


def load_criteria(path: Path = config.CRITERIA_PATH) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def load_schema(path: Path = config.OUTPUT_SCHEMA_PATH) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def load_script(path: Path = config.SCRIPT_PATH) -> str:
    if not Path(path).exists():
        raise FileNotFoundError(
            f"Không thấy kịch bản tại {path}. Đặt OBEVAL_SCRIPT hoặc chép file kịch bản PDC vào đó."
        )
    return Path(path).read_text(encoding="utf-8-sig").strip()


# Từ khoá Vertex `response_json_schema` không cần / có thể từ chối. Kiểm đầy đủ ở local (validate.py).
# minItems/maxItems = 37 làm Vertex báo "too many states for serving" (đo 09/10) → bỏ, validate.normalize vá.
_DROP_KEYS = {"$comment", "pattern", "description", "minItems", "maxItems", "minimum", "maximum"}


def schema_for_api(schema: dict) -> dict:
    """Bỏ từ khoá không cần và thay `$ref` nội bộ bằng định nghĩa (tránh Vertex từ chối `$defs`)."""
    defs = schema.get("$defs", {})

    def _clean(node):
        if isinstance(node, dict):
            ref = node.get("$ref")
            if isinstance(ref, str) and ref.startswith("#/$defs/"):
                return _clean(defs[ref.split("/")[-1]])
            out = {}
            for k, v in node.items():
                if k == "properties" and isinstance(v, dict):
                    # tên trường (kể cả trường tên "description") giữ nguyên, chỉ làm sạch schema con
                    out[k] = {name: _clean(sub) for name, sub in v.items()}
                elif k in _DROP_KEYS or k == "$defs":
                    continue
                else:
                    out[k] = _clean(v)
            return out
        if isinstance(node, list):
            return [_clean(v) for v in node]
        return node

    return _clean(copy.deepcopy(schema))


def session_meta(tr: Transcript, meta: dict) -> str:
    lines = []
    if meta.get("session_date"):
        lines.append(f"Ngày buổi học: {meta['session_date']}")
    lines.append(f"Thời lượng theo transcript: {fmt_time(tr.duration_sec) if tr.duration_sec else 'không rõ'}")
    lines.append(f"Nguồn transcript: {meta.get('transcript_source') or tr.source_format}")
    lines.append(f"Số đoạn: {len(tr.segments)} · số từ: {tr.word_count}")
    if tr.has_timestamps:
        lines.append("Mốc giờ: có. Trường `timestamp` của bằng chứng ghi đúng dạng HH:MM:SS như trong transcript.")
    else:
        lines.append("Mốc giờ: KHÔNG có. Trường `timestamp` của bằng chứng ghi số dòng dạng #0001 như trong transcript.")
    stats = speaker_stats(tr)
    lines.append("Nhãn người nói (số đoạn / số từ): " + "; ".join(
        f"{k}: {v['segments']} / {v['words']}" for k, v in stats.items()))
    lines.append("Lưu ý: phụ huynh và con có thể dùng chung một thiết bị nên chung một nhãn.")
    if meta.get("mentor_label"):
        lines.append(f"Nhãn của Mentor (do hệ thống cung cấp): {meta['mentor_label']}")
    g = gaps(tr)
    if g:
        lines.append("Khoảng trống ≥ 60 giây không có lời: " + ", ".join(
            f"{fmt_time(a)}–{fmt_time(b)}" for a, b in g))
    for w in tr.warnings:
        lines.append(f"Cảnh báo dữ liệu: {w}")
    return "\n".join(lines)


def build_user_content(tr: Transcript, meta: dict, criteria: dict, script: str) -> str:
    return (
        "<BASELINE>\n" + json.dumps(criteria, ensure_ascii=False) + "\n</BASELINE>\n\n"
        "<SCRIPT_REFERENCE>\n" + script + "\n</SCRIPT_REFERENCE>\n\n"
        "<SESSION_META>\n" + session_meta(tr, meta) + "\n</SESSION_META>\n\n"
        "<TRANSCRIPT>\n" + render(tr) + "\n</TRANSCRIPT>\n\n"
        "Chấm buổi trên theo đúng quy trình 7 bước. Trả về đúng một đối tượng JSON theo schema."
    )
