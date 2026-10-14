"""Một ca: transcript → prompt → model → kiểm → điểm → báo cáo. Mọi file của ca nằm trong một thư mục."""
from __future__ import annotations

import hashlib
import json
import re
import traceback
import unicodedata
from datetime import datetime
from pathlib import Path

from concurrent.futures import ThreadPoolExecutor

from . import config, dashboard, ensemble, llm, prompt, report, score, transcript, validate, verify


def case_key_from(path: Path, session_date: str | None) -> str:
    """Tên thư mục ca: ngày + tên file (bỏ dấu) + băm đường dẫn → không trùng khi tên file giống nhau."""
    stem = Path(path).stem.replace("Đ", "D").replace("đ", "d")
    stem = "".join(ch for ch in unicodedata.normalize("NFD", stem) if not unicodedata.combining(ch))
    stem = re.sub(r"[^A-Za-z0-9_-]+", "-", stem).strip("-")[:40] or "ca"
    digest = hashlib.sha1(str(Path(path).resolve()).encode("utf-8")).hexdigest()[:6]
    return f"{(session_date or datetime.now().strftime('%Y-%m-%d'))}_{stem}_{digest}"


def _write(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, (bytes, bytearray)):
        path.write_bytes(data)
    elif isinstance(data, str):
        path.write_text(data, encoding="utf-8")
    else:
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _status(case_dir: Path, state: str, **extra) -> None:
    f = case_dir / "status.json"
    cur = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {"history": []}
    cur["state"] = state
    cur["history"].append({"state": state, "at": datetime.now().isoformat(timespec="seconds"), **extra})
    _write(f, cur)


def postprocess(raws: list[dict], tr: transcript.Transcript, criteria_doc: dict, schema: dict):
    """JSON thô của 1..N lần chạy → (kết quả đã kiểm + gộp, điểm, lỗi AI, thống kê trích dẫn, độ ổn định).

    Mỗi lần chạy kiểm schema + vá + kiểm trích dẫn riêng, rồi mới gộp (ensemble.py).
    """
    if isinstance(raws, dict):
        raws = [raws]
    checked, issues = [], []
    qstats: dict[str, int] = {}
    for k, raw in enumerate(raws):
        tag = f"[lần {k + 1}] " if len(raws) > 1 else ""
        issues += [f"{tag}Schema: {m}" for m in validate.schema_errors(raw, schema)]
        result, fix_issues = validate.normalize(raw)
        result, v_issues, qs = verify.verify(result, tr)
        issues += [tag + m for m in fix_issues + v_issues]
        for key, val in qs.items():
            qstats[key] = qstats.get(key, 0) + val
        checked.append(result)
    result, stability = ensemble.aggregate(checked)
    scores = score.compute(result, criteria_doc)
    return result, scores, issues, qstats, stability


def _sum_usage(calls: list[dict]) -> dict:
    out: dict[str, int] = {}
    for c in calls:
        for k, v in (c.get("usage") or {}).items():
            out[k] = out.get(k, 0) + (v or 0)
    return out


def _call_models(system: str, user: str, api_schema: dict, model: str, thinking_budget: int, runs: int) -> list[dict]:
    """Gọi model `runs` lần song song. Lần nào lỗi thì bỏ, còn ≥ 1 lần thành công là chấm tiếp."""
    if runs <= 1:
        return [llm.call(system, user, api_schema, model=model, thinking_budget=thinking_budget)]
    # Đo 09/10: 3 lần gọi song song ở temperature 0 ra CÙNG trạng thái (không độc lập), trong khi
    # cùng prompt gọi lúc khác lệch 8/37 tiêu chí → bộ nhiều lần dùng temperature + seed khác nhau.
    calls, errors = [], []
    with ThreadPoolExecutor(max_workers=runs) as pool:
        futs = [pool.submit(llm.call, system, user, api_schema, model=model, thinking_budget=thinking_budget,
                            temperature=config.ENSEMBLE_TEMPERATURE, seed=1000 + k)
                for k in range(runs)]
        for f in futs:
            try:
                calls.append(f.result())
            except Exception as exc:  # noqa: BLE001
                errors.append(str(exc)[:300])
    if not calls:
        raise llm.LLMError("Mọi lần gọi model đều lỗi: " + " | ".join(errors))
    for c in calls:
        c["sibling_errors"] = errors
    return calls


def run_case(transcript_path: Path, meta: dict, model: str = config.DEFAULT_MODEL,
             thinking_budget: int = config.DEFAULT_THINKING_BUDGET, out_root: Path = config.OUT_ROOT,
             fmt: str = "auto", dry_run: bool = False, replay: Path | None = None,
             runs: int = config.DEFAULT_RUNS) -> dict:
    meta = dict(meta)
    case_key = meta.get("case_id") or case_key_from(transcript_path, meta.get("session_date"))
    meta["case_id"] = case_key
    meta["transcript_path"] = str(Path(transcript_path).resolve())
    case_dir = Path(out_root) / case_key
    case_dir.mkdir(parents=True, exist_ok=True)
    criteria_doc = prompt.load_criteria()
    names = report.Names(criteria_doc)
    _status(case_dir, "processing")
    if not dry_run:  # ca bị dừng giữa chừng vẫn hiện trên bảng điều khiển là "đang xử lý"
        _write(case_dir / "dashboard_row.json", dashboard.make_row(case_key, meta, None, None, "processing", names))
    try:
        tr = transcript.load(transcript_path, fmt)
        if not meta.get("mentor_label") and tr.mentor_label:  # STT chia người nói đã gán vai
            meta["mentor_label"] = tr.mentor_label
        meta["duration_sec"] = tr.duration_sec  # email: mốc kết thúc của hoạt động cuối
        _write(case_dir / "transcript_normalized.txt", transcript.render(tr))
        if not tr.segments:
            raise ValueError("Transcript rỗng — không chấm")
        system = prompt.load_system_prompt()
        user = prompt.build_user_content(tr, meta, criteria_doc, prompt.load_script())
        full_schema = prompt.load_schema()
        api_schema = prompt.schema_for_api(full_schema)
        if dry_run:
            _write(case_dir / "prompt_system.txt", system)
            _write(case_dir / "prompt_user.txt", user)
            _write(case_dir / "schema_api.json", api_schema)
            _status(case_dir, "dry_run")
            return {"case_dir": str(case_dir), "state": "dry_run", "chars": len(system) + len(user),
                    "segments": len(tr.segments), "words": tr.word_count, "warnings": tr.warnings}

        if replay:
            saved = json.loads(Path(replay).read_text(encoding="utf-8"))
            if "runs" in saved:
                calls = saved["runs"]
            elif "data" in saved:
                calls = [saved]
            else:  # file chỉ chứa JSON kết quả trần
                calls = [{"data": saved, "usage": {}, "model": "replay"}]
        else:
            n_tok = llm.count_tokens(model, system, user)
            if n_tok and n_tok > config.MAX_TRANSCRIPT_TOKENS_WARN + 40_000:
                tr.warnings.append(f"Prompt {n_tok} token — bất thường, có thể gộp nhầm nhiều buổi")
            calls = _call_models(system, user, api_schema, model, thinking_budget, runs)
            _write(case_dir / "model_raw.json", {"runs": calls, "prompt_tokens_counted": n_tok})

        result, scores, issues, qstats, stability = postprocess([c["data"] for c in calls], tr, criteria_doc, full_schema)
        if calls[0].get("sibling_errors"):
            issues.insert(0, f"Chỉ {len(calls)}/{len(calls) + len(calls[0]['sibling_errors'])} lần chấm thành công — gộp trên số lần còn lại")
        costs = [c.get("cost_usd_est") for c in calls if c.get("cost_usd_est") is not None]
        run_info = {
            "model": calls[0].get("model"), "model_version": calls[0].get("model_version"),
            "runs": len(calls), "run_errors": calls[0].get("sibling_errors") or [],
            "latency_sec": max((c.get("latency_sec") or 0) for c in calls), "usage": _sum_usage(calls),
            "cost_usd_est": round(sum(costs), 4) if costs else None, "ai_issues": issues, "quote_stats": qstats,
            "stability": stability,
            "transcript_format": tr.source_format, "segments": len(tr.segments), "words": tr.word_count,
            "transcript_warnings": tr.warnings, "finished_at": datetime.now().isoformat(timespec="seconds"),
        }
        _write(case_dir / "result.json", {"meta": meta, "scores": scores, "run": run_info, **result})
        _write(case_dir / "email_mentor.html", report.mentor_email_page(result, scores, meta, names))
        _write(case_dir / "email_mentor.eml", report.mentor_eml(result, scores, meta, names))
        _write(case_dir / "detail.html", report.detail_html(result, scores, meta, names, run_info))
        _write(case_dir / "dashboard_row.json", dashboard.make_row(case_key, meta, result, scores, "done", names))
        _status(case_dir, "done", classification=scores["classification"])
        return {"case_dir": str(case_dir), "state": "done", "overall": scores["overall"],
                "classification": scores["classification_label"], "ne_ratio": scores["ne_ratio"],
                "ai_issues": len(issues), "quotes": qstats, "cost_usd_est": run_info["cost_usd_est"],
                "usage": run_info["usage"], "latency_sec": run_info["latency_sec"], "stability": stability}
    except Exception as exc:  # noqa: BLE001 — ca lỗi phải hiện lên bảng điều khiển, không bỏ qua lặng lẽ
        _write(case_dir / "error.txt", traceback.format_exc())
        _write(case_dir / "dashboard_row.json", dashboard.make_row(case_key, meta, None, None, "error", names))
        _status(case_dir, "error", error=str(exc)[:300])
        return {"case_dir": str(case_dir), "state": "error", "error": str(exc)}


def rescore(case_dir: Path) -> dict:
    """Chạy lại kiểm + điểm + báo cáo từ model_raw.json (đổi ngưỡng/luật mà không gọi lại model)."""
    case_dir = Path(case_dir)
    raw = case_dir / "model_raw.json"
    res_file = case_dir / "result.json"
    if not raw.exists() or not res_file.exists():
        return {"case_dir": str(case_dir), "state": "error",
                "error": "Thiếu model_raw.json hoặc result.json — không tính lại (giữ nguyên kết quả cũ)"}
    meta = json.loads(res_file.read_text(encoding="utf-8"))["meta"]
    if not Path(meta.get("transcript_path", "")).exists():
        return {"case_dir": str(case_dir), "state": "error",
                "error": f"Không thấy transcript gốc {meta.get('transcript_path')} — không tính lại (giữ nguyên kết quả cũ)"}
    return run_case(Path(meta["transcript_path"]), meta, out_root=case_dir.parent, replay=raw)
