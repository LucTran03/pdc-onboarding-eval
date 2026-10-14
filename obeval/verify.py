"""Kiểm mọi trích dẫn của model có thật trong transcript; sửa mốc giờ theo chỗ khớp; hạ nhận định không có căn cứ.

Luật (prompt/README.md §4, sửa theo review đối kháng 2 vòng ngày 09/10 — tool/logs/):
- so trên token đã chuẩn hoá: thường, bỏ dấu câu, bỏ dấu thanh/dấu mũ (hoà ≡ hòa);
- khớp nguyên văn, hoặc gần nguyên văn (≥ 85%, chỉ với đoạn ≥ 5 từ) nhưng KHÔNG được lệch ở chữ phủ định
  ("không", "chưa"…) hay chữ số — khớp gần đúng thì email in lời GỐC trong transcript, không in câu của model;
- trích một đoạn: ≥ 3 từ. Trích có "…": mỗi phần ≥ 2 từ, tổng ≥ 5 từ, các phần cách nhau ≤ 120 từ, đúng thứ tự;
- không vắt qua hai người nói — trừ ca STT gán nhầm vài chữ (đoạn ≥ 8 từ, phần của người kia ≤ 3 từ);
- câu lặp nhiều lần: chọn chỗ gần mốc giờ model khai nhất;
- tiêu chí FF/PF/NF mà KHÔNG có bằng chứng nào khớp → hạ về NE, ghi vào lỗi của AI;
- trích dẫn không khớp bị tách sang `evidence_unverified` (không bao giờ vào email);
- cờ / điểm tốt / gợi ý không còn bằng chứng khớp → tách ra danh sách "chưa xác minh";
- vai người nói in theo bảng gán vai (`data_quality.speaker_mapping`) của chính lần chấm đó.
"""
from __future__ import annotations

import difflib
import re
import unicodedata

from .transcript import MASK, Transcript, fmt_time, line_ref, parse_time

FUZZY_MIN = 0.85
FUZZY_MIN_TOKENS = 5  # đoạn ngắn hơn phải khớp nguyên văn ("dạ vâng ạ" khớp gần đúng ở đâu cũng được)
MIN_QUOTE_TOKENS = 3
MIN_PART_TOKENS = 2
MIN_MULTIPART_TOKENS = 5
MAX_PART_GAP = 120
STT_SLIP_MIN_SPAN = 8
STT_SLIP_MAX_MINORITY = 3
TIME_TOLERANCE_SEC = 90
MAX_IMPROVEMENTS = 3
# Chữ làm đảo nghĩa câu (đã bỏ dấu): lệch ở đây thì không coi là "gần đúng".
# Kiểm trên chữ CÒN DẤU: bỏ dấu thì "khối" ≡ "khỏi", "cha" (bố) ≡ "chả" — trùng giả (đo 09/10).
NEGATIONS = {"không", "chưa", "chẳng", "chả", "đừng", "ko", "hông", "hổng", "k", "đéo", "khỏi"}
ROLE_VI = {"mentor": "Mentor", "parent": "Phụ huynh", "student": "Học sinh",
           "parent_or_student": "Phụ huynh/học sinh", "other": "Người khác"}


def _norm_tokens(text: str, keep_marks: bool = False) -> list[str]:
    """Thường, bỏ [SỐ], bỏ dấu câu, bỏ dấu thanh/dấu mũ (hoà ≡ hòa; model hay đặt dấu khác STT).

    keep_marks=True: giữ dấu (dạng dựng sẵn NFC) — cùng cách tách từ, dùng để nhận chữ phủ định.
    """
    text = unicodedata.normalize("NFC", (text or "").lower()).replace(MASK.lower(), " ")
    if not keep_marks:
        text = text.replace("đ", "d")
        text = "".join(ch for ch in unicodedata.normalize("NFD", text) if not unicodedata.combining(ch))
    text = re.sub(r"[^\w\s]", " ", text)
    return text.split()


def _raw_like(text: str, stripped: list[str]) -> list[str]:
    raw = _norm_tokens(text, keep_marks=True)
    return raw if len(raw) == len(stripped) else stripped


def _safe_diff(q: list[str], win: list[str], q_raw: list[str], win_raw: list[str]) -> bool:
    """Khác biệt giữa trích dẫn và transcript không chạm chữ phủ định hay chữ số (xét trên chữ còn dấu)."""
    for op, a1, a2, b1, b2 in difflib.SequenceMatcher(None, q, win, autojunk=False).get_opcodes():
        if op == "equal":
            continue
        for tok in q_raw[a1:a2] + win_raw[b1:b2]:
            if tok in NEGATIONS or any(ch.isdigit() for ch in tok):
                return False
    return True


class QuoteIndex:
    def __init__(self, tr: Transcript):
        self.tr = tr
        self.tokens: list[str] = []
        self.raw_tokens: list[str] = []    # cùng vị trí, còn dấu — để nhận chữ phủ định
        self.tok_seg: list[int] = []
        self.tok_word: list[int] = []      # chỉ số từ gốc (tách theo khoảng trắng) trong đoạn
        self.seg_words: list[list[str]] = []
        for i, s in enumerate(tr.segments):
            words = s.text.split()
            self.seg_words.append(words)
            for w_i, w in enumerate(words):
                toks = _norm_tokens(w)
                for tok, raw in zip(toks, _raw_like(w, toks)):
                    self.tokens.append(tok)
                    self.raw_tokens.append(raw)
                    self.tok_seg.append(i)
                    self.tok_word.append(w_i)
        self._matcher = difflib.SequenceMatcher(None, autojunk=False)
        self._matcher.set_seq2(self.tokens)

    # -------------------------------------------------------------- tiện ích
    def _speaker_ok(self, toks: list[int]) -> bool:
        """Các token không thuộc hai người nói — trừ ca STT gán nhầm vài chữ ở ranh giới."""
        count: dict[str, int] = {}
        for k in toks:
            lab = self.tr.segments[self.tok_seg[k]].speaker
            if lab:
                count[lab] = count.get(lab, 0) + 1
        if len(count) <= 1:
            return True
        minority = min(count.values()) if len(count) == 2 else 0
        # STT gán nhầm vài chữ ở ranh giới: phần người kia ≤ 3 từ VÀ ≤ 25% đoạn trích
        # ("đăng ký ngay | không ạ em từ chối" = 3/8 → vẫn chặn, đó là ghép lời 2 người).
        return (len(count) == 2 and len(toks) >= STT_SLIP_MIN_SPAN
                and minority <= STT_SLIP_MAX_MINORITY and minority * 4 <= len(toks))

    def _time_of(self, tok: int) -> float | None:
        return self.tr.segments[self.tok_seg[tok]].start

    def original_text(self, lo: int, hi: int) -> str:
        """Lời gốc trong transcript ứng với token [lo, hi)."""
        out, cur_seg, first_w = [], None, None
        for k in range(lo, min(hi, len(self.tokens))):
            seg, w = self.tok_seg[k], self.tok_word[k]
            if seg != cur_seg:
                if cur_seg is not None:
                    out.append(" ".join(self.seg_words[cur_seg][first_w:last_w + 1]))
                cur_seg, first_w = seg, w
            last_w = w
        if cur_seg is not None:
            out.append(" ".join(self.seg_words[cur_seg][first_w:last_w + 1]))
        return " ".join(out)

    def _exact_positions(self, p: list[str], tok_from: int, tok_to: int | None = None) -> list[int]:
        n, out = len(p), []
        first = p[0]
        end = len(self.tokens) - n + 1 if tok_to is None else min(len(self.tokens) - n + 1, tok_to)
        for k in range(tok_from, end):
            if self.tokens[k] == first and self.tokens[k:k + n] == p and self._speaker_ok(list(range(k, k + n))):
                out.append(k)
        return out

    def _fuzzy_position(self, q: list[str], tok_from: int, tok_to: int | None = None,
                        q_raw: list[str] | None = None) -> tuple[int | None, int, float]:
        """→ (vị trí bắt đầu, độ dài cửa sổ, tỉ lệ) của chỗ khớp gần đúng tốt nhất (hoặc None)."""
        if len(q) < FUZZY_MIN_TOKENS or not self.tokens:
            return None, 0, 0.0
        q_raw = q_raw if q_raw is not None and len(q_raw) == len(q) else q
        b_end = len(self.tokens) if tok_to is None else min(len(self.tokens), tok_to + len(q))
        self._matcher.set_seq1(q)
        m = self._matcher.find_longest_match(0, len(q), tok_from, b_end)
        if m.size < 3:
            return None, 0, m.size / len(q)
        best = (None, 0, 0.0)
        base = m.b - m.a
        for shift in (-2, -1, 0, 1, 2):
            for extra in (-1, 0, 1):
                lo = max(tok_from, base + shift)
                hi = lo + len(q) + extra
                win = self.tokens[lo:hi]
                if not win or not self._speaker_ok(list(range(lo, min(hi, len(self.tokens))))):
                    continue
                r = difflib.SequenceMatcher(None, q, win, autojunk=False).ratio()
                # Chữ phủ định ngay sát cửa sổ cũng tính: cắt cửa sổ bỏ "không" không được lách luật.
                # Phủ định ĐỨNG TRƯỚC cửa sổ ≤ 3 từ ("không dám cam kết") cũng tính. Phía sau thì không:
                # câu hỏi tiếng Việt hay kết thúc bằng "không" ("…khi đi thi không?").
                ctx = self.raw_tokens[max(0, lo - 3):hi]
                same_neg = sorted(t for t in q_raw if t in NEGATIONS) == sorted(t for t in ctx if t in NEGATIONS)
                if r > best[2] and r >= FUZZY_MIN and same_neg and _safe_diff(q, win, q_raw, self.raw_tokens[lo:hi]):
                    best = (lo, len(win), r)
        return best if best[0] is not None else (None, 0, best[2])

    # -------------------------------------------------------------- API
    def locate(self, quote: str, claimed_sec: float | None = None) -> tuple[str, int | None, float, list[tuple[int, int]]]:
        """Trả (kết quả, chỉ số đoạn khớp, tỉ lệ, các khoảng token khớp).

        kết quả ∈ exact / fuzzy / not_found / too_short / empty.
        """
        pieces = [(t, _raw_like(x, t)) for x in re.split(r"\.\.\.|…", quote or "") for t in [_norm_tokens(x)] if t]
        parts = [t for t, _ in pieces]
        parts_raw = [r for _, r in pieces]
        if not parts:
            return "empty", None, 0.0, []
        total = sum(len(p) for p in parts)
        if total < MIN_QUOTE_TOKENS or (len(parts) > 1 and (total < MIN_MULTIPART_TOKENS
                                                          or min(len(p) for p in parts) < MIN_PART_TOKENS)):
            return "too_short", None, 0.0, []

        first = parts[0]
        starts = [(k, len(first), 1.0) for k in self._exact_positions(first, 0)]
        if starts and claimed_sec is not None and len(starts) > 1:
            starts.sort(key=lambda s: abs((self._time_of(s[0]) if self._time_of(s[0]) is not None else 1e9) - claimed_sec))
        if not starts:
            pos, ln, ratio = self._fuzzy_position(first, 0, q_raw=parts_raw[0])
            if pos is None:
                return "not_found", None, ratio, []
            starts = [(pos, ln, ratio)]

        for start, ln0, r0 in starts[:5]:  # thử vài chỗ khớp đầu cho các phần sau "…"
            spans, worst, ok = [(start, start + ln0)], r0, True
            tok_from = start + ln0
            for p, p_raw in zip(parts[1:], parts_raw[1:]):
                limit = tok_from + MAX_PART_GAP
                nxt = self._exact_positions(p, tok_from, limit)
                if nxt:
                    spans.append((nxt[0], nxt[0] + len(p)))
                    tok_from = nxt[0] + len(p)
                    continue
                pos, ln, ratio = self._fuzzy_position(p, tok_from, limit, q_raw=p_raw)
                if pos is None:
                    ok = False
                    break
                worst = min(worst, ratio)
                spans.append((pos, pos + ln))
                tok_from = pos + ln
            if ok and len(spans) > 1:
                ok = self._speaker_ok([k for lo, hi in spans for k in range(lo, hi)])
            if ok:
                return ("exact" if worst == 1.0 else "fuzzy"), self.tok_seg[start], worst, spans
        return "not_found", None, 0.0, []


def _seg_ref(tr: Transcript, idx: int) -> str:
    s = tr.segments[idx]
    return fmt_time(s.start) if s.start is not None else line_ref(idx)


def check_evidence(ev: dict, qi: QuoteIndex, roles: dict[str, str] | None = None) -> dict:
    """Gắn `verified`, `match`; sửa `timestamp` theo chỗ khớp thật; trích gần đúng → thay bằng lời gốc."""
    claimed = parse_time(ev.get("timestamp"))
    result, idx, ratio, spans = qi.locate(ev.get("quote", ""), claimed)
    ev["match"] = result
    ev["verified"] = result in ("exact", "fuzzy")
    if not ev["verified"] or idx is None or idx < 0:
        return ev
    if result == "fuzzy":
        ev["quote_model"] = ev.get("quote")
        ev["quote"] = " … ".join(qi.original_text(lo, hi) for lo, hi in spans)
    seg = qi.tr.segments[idx]
    true_ref = _seg_ref(qi.tr, idx)
    wrong = (claimed is None or abs(claimed - seg.start) > TIME_TOLERANCE_SEC) if seg.start is not None \
        else ev.get("timestamp") != true_ref
    if wrong:
        ev["timestamp_model"] = ev.get("timestamp")
        ev["timestamp"] = true_ref
        ev["timestamp_corrected"] = True
    if seg.speaker:
        ev["speaker_label"] = seg.speaker
        role = (roles or {}).get(seg.speaker)
        if role:
            if ev.get("speaker") and ev.get("speaker") != ROLE_VI.get(role, role):
                ev["speaker_model"] = ev.get("speaker")
            ev["speaker"] = ROLE_VI.get(role, role)
    return ev


STAT_KEYS = ("exact", "fuzzy", "not_found", "too_short", "empty")


def verify(result: dict, tr: Transcript) -> tuple[dict, list[str], dict]:
    """Trả (kết quả đã kiểm, lỗi của AI, thống kê trích dẫn)."""
    qi = QuoteIndex(tr)
    roles = {str(m.get("label")): str(m.get("role")) for m in (result.get("data_quality") or {}).get("speaker_mapping") or []
             if isinstance(m, dict) and m.get("label") and m.get("role")}
    issues: list[str] = []
    stats = {"total": 0, **{k: 0 for k in STAT_KEYS}}

    def _check(item: dict) -> int:
        """Kiểm và tách: `evidence` chỉ còn trích dẫn khớp, phần còn lại sang `evidence_unverified`."""
        good, bad = [], []
        for ev in item.get("evidence") or []:
            if not isinstance(ev, dict):
                continue
            check_evidence(ev, qi, roles)
            stats["total"] += 1
            stats[ev["match"]] += 1
            (good if ev["verified"] else bad).append(ev)
        item["evidence"] = good
        if bad:
            item["evidence_unverified"] = bad
        return len(good)

    for c in result["criteria"]:
        n_ok = _check(c)
        if c["status"] in ("FF", "PF", "NF") and n_ok == 0:
            if c.get("evidence_unverified"):
                issues.append(f"{c['id']}: {len(c['evidence_unverified'])} trích dẫn không có trong transcript → NE")
                c["downgraded"] = "quote_unverified"
            else:
                issues.append(f"{c['id']}: trạng thái {c['status']} nhưng không có bằng chứng → NE")
                c["downgraded"] = "no_evidence"
            c["status_model"], c["status"] = c["status"], "NE"
            c["goal_achieved"] = "unknown"

    for lk in result["links"]:
        _check(lk)

    def _split(items, label):
        kept, dropped = [], []
        for it in items:
            if _check(it) == 0:
                dropped.append(it)
                issues.append(f"{label} {it.get('id') or it.get('criterion_id')}: không có trích dẫn khớp transcript → không gửi Mentor")
            else:
                kept.append(it)
        return kept, dropped

    result["flags"], result["flags_unverified"] = _split(result.get("flags") or [], "Cờ")
    result["strengths"], result["strengths_unverified"] = _split(result.get("strengths") or [], "Điểm tốt")
    imps, result["improvements_unverified"] = _split(result.get("improvements") or [], "Gợi ý")
    if len(imps) > MAX_IMPROVEMENTS:
        issues.append(f"Model trả {len(imps)} gợi ý có căn cứ — giữ {MAX_IMPROVEMENTS} gợi ý đầu")
    result["improvements"] = imps[:MAX_IMPROVEMENTS]
    result["improvements_extra"] = imps[MAX_IMPROVEMENTS:]  # dự phòng khi gộp nhiều lần chấm
    for dev in (result.get("sequence") or {}).get("deviations") or []:
        _check(dev)
    return result, issues, stats
