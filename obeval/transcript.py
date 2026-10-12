"""Đọc transcript từ nhiều nguồn về một dạng chung, che số nhạy cảm, dựng văn bản gửi model.

Nguồn hỗ trợ (``fmt="auto"`` tự nhận):
- JSON STT có ``segments`` (temp-transcript ``transcripts/<sid>.json``, STT tách người nói mới);
- JSON hàng bảng ``transcripts`` DB TeenCareParent (``transcript`` = mảng đoạn, ``start_time = -1``);
- JSON mảng đoạn trần;
- văn bản ``[HH:MM:SS] Người nói: lời``;
- văn bản Google Meet (dòng chỉ có mốc giờ, rồi các dòng ``Tên: lời``);
- SRT / WebVTT.
"""
from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Segment:
    start: float | None
    end: float | None
    speaker: str
    text: str


@dataclass
class Transcript:
    segments: list[Segment]
    source_format: str
    duration_sec: float | None = None
    warnings: list[str] = field(default_factory=list)

    @property
    def has_timestamps(self) -> bool:
        return any(s.start is not None for s in self.segments)

    @property
    def word_count(self) -> int:
        return sum(len(s.text.split()) for s in self.segments)


# ---------------------------------------------------------------- thời gian

_TS_RE = re.compile(r"^(?:(\d{1,2}):)?(\d{1,2}):(\d{2})(?:[.,](\d{1,3}))?$")


def parse_time(value) -> float | None:
    """Giây (số) hoặc 'HH:MM:SS(.mmm)' / 'MM:SS' → giây. -1 / rỗng → None."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return None if value < 0 else float(value)
    text = str(value).strip()
    if not text:
        return None
    try:
        num = float(text)
        return None if num < 0 else num
    except ValueError:
        pass
    m = _TS_RE.match(text)
    if not m:
        return None
    h, mnt, s, frac = m.groups()
    total = int(h or 0) * 3600 + int(mnt) * 60 + int(s)
    if frac:
        total += int(frac) / (10 ** len(frac))
    return float(total)


def fmt_time(sec: float | None) -> str:
    if sec is None:
        return "--:--:--"
    sec = int(round(sec))
    return f"{sec // 3600:02d}:{sec % 3600 // 60:02d}:{sec % 60:02d}"


# ---------------------------------------------------------------- chuẩn hoá chữ

# Ký tự Cyrillic trông giống Latin (STT v3 từng lẫn vào chữ Việt — review 08/10).
_HOMOGLYPHS = str.maketrans({
    "а": "a", "е": "e", "о": "o", "р": "p", "с": "c", "у": "y", "х": "x", "і": "i",
    "А": "A", "Е": "E", "О": "O", "Р": "P", "С": "C", "Х": "X", "Т": "T", "Н": "H",
    "К": "K", "М": "M", "В": "B",
})

# Một "cụm số": các nhóm chữ số nối bằng đúng 1 ký tự cách/chấm/phẩy/gạch (vd 0912 345 678, 1234-5678-9012).
# Dính chữ phía trước vẫn bắt ("sdt0912345678"). Che khi cụm có ≥ 9 chữ số (SĐT, số tài khoản), TRỪ:
#   - giá tiền: nhóm hàng nghìn ngăn bằng "." hoặc "," (120.000.000), hoặc ngay sau là đơn vị tiền;
#   - dãy số đếm / điểm: có nhóm 1 chữ số ("8 9 7 8 9 10").
# Hai giá đứng cạnh nhau ("36.000.000 12.000.000") được tách theo dấu cách rồi xét từng phần.
# Dạng số viết bằng chữ ("không chín một hai…") KHÔNG che được — giới hạn đã biết.
_NUM_RUN_RE = re.compile(r"(?<![\d+])\+?\d+(?:[ .,\-]\d+)*(?!\d)")
_MONEY_AFTER = re.compile(r"^\s*(đồng|dong\b|đ\b|vnd|vnđ|triệu|trieu|tr\b|nghìn|nghin|ngàn|ngan\b|k\b|usd|\$|%)", re.I)
MASK = "[SỐ]"


def clean_text(text: str) -> str:
    text = unicodedata.normalize("NFC", str(text)).translate(_HOMOGLYPHS)
    return re.sub(r"\s+", " ", text).strip()


def _is_thousands(run: str) -> bool:
    groups = re.split(r"[.,]", run)
    return (len(groups) >= 2 and 1 <= len(groups[0]) <= 3 and not groups[0].startswith("0")
            and all(len(g) == 3 and g.isdigit() for g in groups[1:]) and len(set(re.findall(r"[.,]", run))) == 1)


def _should_mask(run: str, after: str) -> bool:
    digits = re.sub(r"\D", "", run)
    if len(digits) < 9:
        return False
    # Dạng SĐT (0xx / +84 / 84, 10–12 số): luôn che, kể cả khi STT ghi "k", "tr" phía sau.
    if (digits.startswith("0") and len(digits) in (10, 11)) or (digits.startswith("84") and len(digits) in (11, 12)):
        return not _is_thousands(run)
    if _MONEY_AFTER.match(after):
        return False
    if " " in run and re.search(r"[.,]", run):  # nhiều số đứng cạnh nhau → xét từng số
        return any(_should_mask(p, "") for p in run.split(" "))
    groups = re.split(r"[ .,\-]", run.lstrip("+"))
    if len(groups) > 2 and any(len(g) == 1 for g in groups[1:]):
        return False
    return run.startswith("+") or not _is_thousands(run)


def mask_numbers(text: str) -> tuple[str, int]:
    out, n, last = [], 0, 0
    for m in _NUM_RUN_RE.finditer(text):
        if not _should_mask(m.group(0), text[m.end():m.end() + 8]):
            continue
        out.append(text[last:m.start()])
        out.append(MASK)
        last = m.end()
        n += 1
    out.append(text[last:])
    return "".join(out), n


# ---------------------------------------------------------------- JSON

_SEG_LIST_KEYS = ("segments", "utterances", "results", "transcript", "chunks", "items")
_START_KEYS = ("start", "start_time", "startTime", "start_sec", "begin", "offset")
_END_KEYS = ("end", "end_time", "endTime", "end_sec")
_MS_KEYS = ("start_ms", "startMs", "start_time_ms")
_END_MS_KEYS = ("end_ms", "endMs", "end_time_ms")
_SPK_KEYS = ("speaker", "speaker_label", "speakerLabel", "spk", "role", "speaker_name", "name")
_TEXT_KEYS = ("text", "transcript", "content", "sentence")


def _first(d: dict, keys):
    for k in keys:
        if k in d and d[k] not in (None, ""):
            return d[k]
    return None


def _segments_from_list(items: list) -> list[Segment]:
    segs: list[Segment] = []
    for it in items:
        if isinstance(it, str):
            segs.append(Segment(None, None, "", it))
            continue
        if not isinstance(it, dict):
            continue
        text = _first(it, _TEXT_KEYS)
        if not isinstance(text, str):
            continue
        ms = _first(it, _MS_KEYS)
        if ms is not None:
            start = parse_time(ms)
            start = start / 1000 if start is not None else None
            end_ms = parse_time(_first(it, _END_MS_KEYS))
            end = end_ms / 1000 if end_ms is not None else None
        else:
            start = parse_time(_first(it, _START_KEYS))
            end = parse_time(_first(it, _END_KEYS))
        spk = _first(it, _SPK_KEYS)
        segs.append(Segment(start, end, str(spk) if spk is not None else "", text))
    return segs


def _maybe_ms(segs: list[Segment], duration: float | None) -> list[Segment]:
    """Một số nguồn ghi mili-giây trong khoá 'start'. Buổi onboarding < 6 giờ."""
    starts = [s.start for s in segs if s.start is not None]
    if not starts:
        return segs
    limit = (duration * 2) if duration else 6 * 3600
    if max(starts) > limit and max(starts) / 1000 <= 6 * 3600:
        for s in segs:
            s.start = s.start / 1000 if s.start is not None else None
            s.end = s.end / 1000 if s.end is not None else None
    return segs


def _parse_json(data) -> tuple[list[Segment], str, float | None]:
    duration = None
    if isinstance(data, list):
        return _maybe_ms(_segments_from_list(data), None), "json_list", None
    if not isinstance(data, dict):
        raise ValueError("JSON transcript phải là object hoặc mảng")
    duration = parse_time(data.get("duration_sec") or data.get("duration"))
    for key in _SEG_LIST_KEYS:
        val = data.get(key)
        if isinstance(val, dict) and val:  # {"transcript": {"segments": [...]}}
            try:
                return _parse_json(val)
            except ValueError:
                pass
        if isinstance(val, str) and val.lstrip()[:1] in ("[", "{"):
            # cột jsonb xuất ra dạng chuỗi JSON (vd hàng bảng transcripts copy từ SQL Editor)
            try:
                val = json.loads(val)
            except json.JSONDecodeError:
                pass
            if isinstance(val, dict) and val:
                try:
                    return _parse_json(val)
                except ValueError:
                    pass
        if isinstance(val, list) and val:
            segs = _segments_from_list(val)
            if segs:
                fmt = "db_row" if key == "transcript" else f"json_{key}"
                return _maybe_ms(segs, duration), fmt, duration
    # Chỉ có chuỗi transcript, không có đoạn → một khối không mốc giờ.
    text = data.get("transcript") or data.get("text")
    if isinstance(text, str) and text.strip():
        return [Segment(None, None, "", text)], "json_text_only", duration
    raise ValueError("Không tìm thấy lời thoại trong JSON (segments/transcript/text)")


# ---------------------------------------------------------------- văn bản

_BRACKET_LINE = re.compile(
    r"^\s*[\[(]?(\d{1,2}:\d{2}(?::\d{2})?(?:[.,]\d{1,3})?)[\])]?\s*[-–]?\s*(?:([^:\n]{1,60}?):\s+)?(.*)$"
)
_TS_ONLY = re.compile(r"^\s*[\[(]?(\d{1,2}:\d{2}(?::\d{2})?)[\])]?\s*$")
_SPEAKER_LINE = re.compile(r"^\s*([^:\n]{1,60}?):\s+(.+)$")
_SRT_TIME = re.compile(
    r"((?:\d{1,2}:)?\d{2}:\d{2}[.,]\d{1,3})\s*-->\s*((?:\d{1,2}:)?\d{2}:\d{2}[.,]\d{1,3})"
)
_VTT_VOICE = re.compile(r"^<v(?:\.[^\s>]+)?\s+([^>]+)>(.*?)(?:</v>)?$")
_ROLE_WORDS = {"mentor", "ph", "phụ huynh", "hs", "học sinh", "con", "mẹ", "bố", "ba", "thầy", "cô", "unknown"}
_ROLE_PREFIX = {"mẹ", "bố", "ba", "thầy", "cô", "con", "anh", "chị", "bé", "em", "ông", "bà", "dì", "chú", "bác", "mentor"}
# Từ mở đầu câu thường gặp trước dấu ":" mà không phải tên người ("Lưu ý:", "Ví dụ:", "Bước một:").
_NOT_NAME_START = {"lưu", "ví", "bước", "chú", "ghi", "câu", "phần", "mục", "kết", "tóm", "nội", "vâng", "dạ", "toán", "môn"}


def _looks_like_speaker(name: str, known: set[str], lenient: bool = False) -> bool:
    """'Tên: lời' chỉ là người nói khi tên giống nhãn thật — tránh 'bước một là: hỏi gia đình', 'Bước 1: …'.

    Nhận khi: tên xuất hiện ≥ 2 lần làm nhãn trong file (`known`, kể cả tên viết thường như
    "Nguyễn thị Thu"); vai/nhãn máy (Mentor, SPEAKER_00, SĐT đã che); vai + tên ("mẹ bé An");
    hoặc họ tên 2–4 từ viết hoa chữ đầu, không có số.
    """
    name = name.strip()
    words = name.split()
    if not name or len(words) > 6 or re.search(r"[,.?!;\"“”]", name):
        return False
    if name in known or name.lower() in _ROLE_WORDS or name == MASK:
        return True
    if re.fullmatch(r"(?i)(speaker|spk|người nói)[\s_-]*\w+", name) or re.fullmatch(r"\+?[\d ]{6,}", name):
        return True
    if any(ch.isdigit() for ch in name) or len(words) > 4:
        return False
    if words[0].lower() in _ROLE_PREFIX and len(words) >= 2 and words[-1][:1].isupper():
        return True
    # Meet: mỗi dòng là một lượt nói, tên hiển thị tuỳ người đặt ("Nguyễn thị Thu"). Tên 1 từ
    # ("Toán:", "Vâng:", "Lưu ý:" là câu tiếp nối) chỉ nhận khi xuất hiện ≥ 2 lần (đã xét ở `known`).
    if lenient and len(words) >= 2 and words[0][:1].isupper() and words[0].lower() not in _NOT_NAME_START:
        return True
    return len(words) >= 2 and all(w[:1].isupper() for w in words)


def _frequent_names(lines: list[str]) -> set[str]:
    """Nhãn xuất hiện ≥ 2 lần ở đầu dòng ("Tên: …" hoặc "[giờ] Tên: …")."""
    cnt: dict[str, int] = {}
    for ln in lines:
        m = _BRACKET_LINE.match(ln)
        name = (m.group(2) if m and m.group(2) else None) or (_SPEAKER_LINE.match(ln).group(1) if _SPEAKER_LINE.match(ln) else None)
        if name:
            name = name.strip()
            if 0 < len(name.split()) <= 6 and not re.search(r"[,.?!;\"“”]", name):
                cnt[name] = cnt.get(name, 0) + 1
    return {k for k, v in cnt.items() if v >= 2}


def _parse_srt_vtt(text: str) -> list[Segment]:
    segs: list[Segment] = []
    blocks = re.split(r"\n\s*\n", text.replace("\r\n", "\n"))
    known = _frequent_names([" ".join(b.strip().split("\n")[1:]) for b in blocks])
    for block in blocks:
        lines = [ln for ln in block.strip().split("\n") if ln.strip()]
        for i, ln in enumerate(lines):
            m = _SRT_TIME.search(ln)
            if not m:
                continue
            body = " ".join(lines[i + 1:]).strip()
            spk = ""
            v = _VTT_VOICE.match(body)
            if v:
                spk, body = v.group(1).strip(), v.group(2).strip()
            else:
                sl = _SPEAKER_LINE.match(body)
                if sl and _looks_like_speaker(sl.group(1), known):
                    spk, body = sl.group(1).strip(), sl.group(2).strip()
            body = re.sub(r"</?[a-zA-Z][^>]*>", "", body).strip()  # thẻ định dạng VTT
            if body:
                segs.append(Segment(parse_time(m.group(1)), parse_time(m.group(2)), spk, body))
            break
    return segs


def _parse_meet(lines: list[str]) -> list[Segment]:
    """Google Meet: mốc giờ đứng riêng một dòng, các dòng sau là "Tên: lời"."""
    segs: list[Segment] = []
    seen: set[str] = _frequent_names(lines)
    cur = None
    for ln in lines:
        if not ln.strip():
            continue
        m = _TS_ONLY.match(ln)
        if m:
            cur = parse_time(m.group(1))
            continue
        sl = _SPEAKER_LINE.match(ln)
        if sl and _looks_like_speaker(sl.group(1), seen, lenient=True):
            seen.add(sl.group(1).strip())
            segs.append(Segment(cur, None, sl.group(1).strip(), sl.group(2).strip()))
        elif segs:
            segs[-1].text += " " + ln.strip()
        elif cur is not None:
            segs.append(Segment(cur, None, "", ln.strip()))
        # còn lại: dòng tiêu đề trước mốc giờ đầu tiên ("<Tên cuộc họp> - Transcript") → bỏ
    return segs


def _parse_lines(lines: list[str]) -> tuple[list[Segment], str]:
    """Văn bản `[HH:MM:SS] Tên: lời` hoặc `Tên: lời` hoặc chữ trơn."""
    segs: list[Segment] = []
    seen: set[str] = _frequent_names(lines)
    timed = 0
    for ln in lines:
        if not ln.strip():
            continue
        m = _BRACKET_LINE.match(ln)
        if m and m.group(3).strip():
            timed += 1
            spk, body = (m.group(2) or "").strip(), m.group(3).strip()
            if spk and not _looks_like_speaker(spk, seen):
                spk, body = "", f"{spk}: {body}"
            if spk:
                seen.add(spk)
            segs.append(Segment(parse_time(m.group(1)), None, spk, body))
            continue
        sl = _SPEAKER_LINE.match(ln)
        if sl and _looks_like_speaker(sl.group(1), seen):
            seen.add(sl.group(1).strip())
            segs.append(Segment(None, None, sl.group(1).strip(), sl.group(2).strip()))
        elif segs:
            segs[-1].text += " " + ln.strip()
        else:
            segs.append(Segment(None, None, "", ln.strip()))
    return segs, ("timed_text" if timed else "plain_text")


def _parse_text(text: str, fmt: str = "auto") -> tuple[list[Segment], str]:
    lines = text.replace("\r\n", "\n").split("\n")
    looks_srt = (text.lstrip().upper().startswith("WEBVTT") or len(_SRT_TIME.findall(text)) >= 2
                 or bool(re.match(r"^\s*\d+\s*\n\s*" + _SRT_TIME.pattern, text)))
    if fmt == "srt" or (fmt == "auto" and looks_srt):
        segs = _parse_srt_vtt(text)
        if segs or fmt == "srt":
            return segs, "srt_vtt"
    if fmt == "meet" or (fmt == "auto" and sum(1 for ln in lines if _TS_ONLY.match(ln)) >= 2):
        return _parse_meet(lines), "meet_text"
    return _parse_lines(lines)


# ---------------------------------------------------------------- API

def load(path: str | Path, fmt: str = "auto") -> Transcript:
    path = Path(path)
    raw = path.read_text(encoding="utf-8-sig")
    duration = None
    if fmt not in ("auto", "json", "text", "meet", "srt"):
        raise ValueError(f"fmt không hỗ trợ: {fmt}")
    data = None
    if fmt == "json":
        data = json.loads(raw)
    elif fmt == "auto" and raw.lstrip()[:1] in ("[", "{"):
        try:  # "[00:01:02] ..." cũng mở đầu bằng "[" nhưng là văn bản
            data = json.loads(raw)
        except json.JSONDecodeError:
            data = None
    if data is not None:
        segs, source, duration = _parse_json(data)
    else:
        segs, source = _parse_text(raw, fmt)
    return finalize(segs, source, duration)


def finalize(segs: list[Segment], source: str, duration: float | None = None) -> Transcript:
    out: list[Segment] = []
    masked = 0
    for s in segs:
        text = clean_text(s.text)
        if not text:
            continue
        text, n = mask_numbers(text)
        speaker, n2 = mask_numbers(clean_text(s.speaker))  # Meet gọi bằng điện thoại: nhãn là SĐT
        masked += n + n2
        out.append(Segment(s.start, s.end, speaker or "", text))
    # Đoạn có mốc giờ: sắp theo thời gian (đoạn không mốc giữ nguyên vị trí tương đối).
    if out and all(s.start is not None for s in out):
        out.sort(key=lambda s: s.start)
    tr = Transcript(out, source, duration)
    if masked:
        tr.warnings.append(f"Đã che {masked} dãy số (SĐT / số tài khoản) thành {MASK}")
    if not out:
        tr.warnings.append("Transcript rỗng")
    elif not tr.has_timestamps:
        tr.warnings.append("Transcript không có mốc giờ — bằng chứng sẽ dùng số dòng #n")
    if out and not any(s.speaker for s in out):
        tr.warnings.append("Transcript không có nhãn người nói — model phải suy vai từ ngữ cảnh")
    if tr.duration_sec is None and tr.has_timestamps:
        last = max((s.end or s.start or 0) for s in out)
        tr.duration_sec = last
    return tr


def line_ref(i: int) -> str:
    return f"#{i + 1:04d}"


def render(tr: Transcript) -> str:
    """Văn bản gửi model: mỗi đoạn một dòng `[HH:MM:SS] NHÃN: lời` (không mốc → `[#0001]`)."""
    rows = []
    for i, s in enumerate(tr.segments):
        ts = fmt_time(s.start) if s.start is not None else line_ref(i)
        spk = s.speaker or "?"
        rows.append(f"[{ts}] {spk}: {s.text}")
    return "\n".join(rows)


def gaps(tr: Transcript, min_gap: float = 60.0) -> list[tuple[float, float]]:
    """Khoảng trống ≥ min_gap giây giữa hai đoạn liên tiếp."""
    res = []
    timed = [s for s in tr.segments if s.start is not None]
    for a, b in zip(timed, timed[1:]):
        a_end = a.end if a.end is not None else a.start
        if b.start - a_end >= min_gap:
            res.append((a_end, b.start))
    return res


def speaker_stats(tr: Transcript) -> dict[str, dict]:
    stats: dict[str, dict] = {}
    for s in tr.segments:
        st = stats.setdefault(s.speaker or "?", {"segments": 0, "words": 0})
        st["segments"] += 1
        st["words"] += len(s.text.split())
    return stats
