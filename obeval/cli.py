"""Lệnh: run · batch · rescore · dashboard · compare · human-template · check-vertex."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import config, dashboard, llm, pipeline, prompt, report
from . import compare as cmp_mod

TRANSCRIPT_EXT = {".json", ".txt", ".srt", ".vtt", ".md"}


def _meta(args) -> dict:
    m = {"session_date": args.session_date, "mentor_name": args.mentor_name, "mentor_email": args.mentor_email,
         "mentor_label": args.mentor_label, "detail_url": args.detail_url, "transcript_source": args.source}
    if getattr(args, "case_id", None):
        m["case_id"] = args.case_id
    return {k: v for k, v in m.items() if v}


def _print(obj) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2, default=str))


def cmd_run(args) -> int:
    res = pipeline.run_case(Path(args.transcript), _meta(args), model=args.model, thinking_budget=args.thinking,
                            out_root=Path(args.out_root), fmt=args.format, dry_run=args.dry_run,
                            replay=Path(args.replay) if args.replay else None, runs=args.runs)
    _print(res)
    if res["state"] == "done":
        _rebuild_dashboard(Path(args.out_root))
    return 0 if res["state"] in ("done", "dry_run") else 1


def cmd_batch(args) -> int:
    files = sorted(p for p in Path(args.dir).iterdir() if p.suffix.lower() in TRANSCRIPT_EXT)
    if not files:
        print(f"Không có transcript trong {args.dir}")
        return 1
    bad = 0
    for f in files:
        meta = _meta(args)
        meta.pop("case_id", None)
        res = pipeline.run_case(f, meta, model=args.model, thinking_budget=args.thinking,
                                out_root=Path(args.out_root), fmt=args.format, dry_run=args.dry_run, runs=args.runs)
        bad += res["state"] == "error"
        print(f"{f.name}: {res['state']} {score_str(res)}")
    _rebuild_dashboard(Path(args.out_root))
    return 1 if bad else 0


def score_str(res: dict) -> str:
    if res.get("state") != "done":
        return res.get("error", "")
    o = res.get("overall")
    return f"{'—' if o is None else f'{o * 100:.0f}%'} · {res.get('classification')} · ~{res.get('cost_usd_est')} USD"


def cmd_rescore(args) -> int:
    res = pipeline.rescore(Path(args.case_dir))
    _print(res)
    _rebuild_dashboard(Path(args.case_dir).parent)
    return 0 if res["state"] == "done" else 1


def _rebuild_dashboard(out_root: Path) -> Path:
    crit = prompt.load_criteria()
    rows = dashboard.collect(out_root, report.Names(crit))
    dashboard.publish_details(out_root)
    page = dashboard.build_html(rows, crit["activities"], config.GOOD_THRESHOLD, crit["criteria"])
    out = out_root / "dashboard.html"
    out.write_text(page, encoding="utf-8")
    print(f"Bảng điều khiển: {out} ({len(rows)} ca)")
    return out


def cmd_dashboard(args) -> int:
    _rebuild_dashboard(Path(args.out_root))
    return 0


def cmd_compare(args) -> int:
    criteria_doc = prompt.load_criteria()
    names = report.Names(criteria_doc)
    pairs = [(Path(args.ai), Path(args.human))] if args.ai else []
    if args.pairs:
        for line in Path(args.pairs).read_text(encoding="utf-8").splitlines():
            if line.strip() and not line.startswith("#"):
                a, h = [x.strip() for x in line.split(",", 1)]
                pairs.append((Path(a), Path(h)))
    out = ["# Đối chiếu AI với người chấm", ""]
    for a, h in pairs:
        ai_path = a / "result.json" if a.is_dir() else a
        ai = json.loads(ai_path.read_text(encoding="utf-8"))
        res = cmp_mod.compare(ai, cmp_mod.load_human(h), criteria_doc)
        out += [cmp_mod.to_markdown(ai.get("meta", {}).get("case_id", ai_path.parent.name), res, names), ""]
    text = "\n".join(out)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
        print(f"Đã ghi {args.out}")
    else:
        print(text)
    return 0


def cmd_template(args) -> int:
    cmp_mod.write_template(Path(args.out), prompt.load_criteria())
    print(f"Đã tạo phiếu chấm tay: {args.out}")
    return 0


def cmd_push_db(args) -> int:
    from . import db
    print(json.dumps(db.push(Path(args.case_dir), args.booking_id, publish=args.publish,
                             with_audit=args.audit), ensure_ascii=False))
    return 0


def cmd_check(args) -> int:
    try:
        print(llm.check_model(args.model))
        return 0
    except Exception as exc:  # noqa: BLE001
        print(f"{args.model}: KHÔNG dùng được — {type(exc).__name__}: {str(exc)[:300]}")
        return 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="obeval", description="Chấm buổi onboarding TeenCare theo brief PDC")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p):
        p.add_argument("--session-date", help="YYYY-MM-DD")
        p.add_argument("--mentor-name", help="Tên hiển thị trong lời chào email (vd 'Thầy Khang')")
        p.add_argument("--mentor-email", help="Địa chỉ đặt sẵn vào bản nháp .eml (không gửi)")
        p.add_argument("--mentor-label", help="Nhãn người nói của Mentor trong transcript, vd SPEAKER_00")
        p.add_argument("--detail-url", help="Đường dẫn xem chi tiết đặt vào email")
        p.add_argument("--source", help="Ghi chú nguồn transcript: stt_v3 | meet | db | gcs ...")
        p.add_argument("--model", default=config.DEFAULT_MODEL)
        p.add_argument("--thinking", type=int, default=config.DEFAULT_THINKING_BUDGET)
        p.add_argument("--runs", type=int, default=config.DEFAULT_RUNS, help="Số lần chấm rồi lấy đa số (mặc định 3)")
        p.add_argument("--out-root", default=str(config.OUT_ROOT))
        p.add_argument("--format", default="auto", choices=["auto", "json", "text", "meet", "srt"])
        p.add_argument("--dry-run", action="store_true", help="Chỉ dựng prompt, không gọi model")

    p = sub.add_parser("run", help="Chấm một transcript")
    p.add_argument("transcript")
    p.add_argument("--case-id")
    p.add_argument("--replay", help="Dùng JSON model đã lưu thay vì gọi model")
    common(p)
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("batch", help="Chấm mọi transcript trong một thư mục")
    p.add_argument("dir")
    common(p)
    p.set_defaults(func=cmd_batch)

    p = sub.add_parser("rescore", help="Tính lại từ model_raw.json của một ca")
    p.add_argument("case_dir")
    p.set_defaults(func=cmd_rescore)

    p = sub.add_parser("dashboard", help="Dựng lại bảng điều khiển")
    p.add_argument("--out-root", default=str(config.OUT_ROOT))
    p.set_defaults(func=cmd_dashboard)

    p = sub.add_parser("compare", help="Đối chiếu AI với người chấm (giai đoạn 1)")
    p.add_argument("--ai", help="Thư mục ca hoặc result.json")
    p.add_argument("--human", help="CSV phiếu chấm tay hoặc answer_key.json")
    p.add_argument("--pairs", help="File nhiều dòng 'ai_case_dir,human_file'")
    p.add_argument("--out")
    p.set_defaults(func=cmd_compare)

    p = sub.add_parser("human-template", help="Tạo phiếu chấm tay CSV cho học thuật")
    p.add_argument("out")
    p.set_defaults(func=cmd_template)

    p = sub.add_parser("push-db", help="Ghi kết quả một ca lên DB đặt lịch (OBEVAL_DB_URL / OBEVAL_DB_KEY)")
    p.add_argument("case_dir")
    p.add_argument("--booking-id", required=True, help="bookings.id của buổi onboarding")
    p.add_argument("--publish", action="store_true", help="Cho Mentor xem ngay (published_at = now)")
    p.add_argument("--audit", action="store_true", help="Đẩy cả bản đầy đủ có trích dẫn (bảng audit, chỉ admin)")
    p.set_defaults(func=cmd_push_db)

    p = sub.add_parser("check-vertex", help="Kiểm model có dùng được trên Vertex công ty (chỉ đọc metadata)")
    p.add_argument("--model", default=config.DEFAULT_MODEL)
    p.set_defaults(func=cmd_check)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
