"""Chạy STT chia người nói (repo SpeechToText, nhánh feat/stt-diarized-pipeline) ngay trên máy cho recording onboarding,
ghi JSON đúng dạng worker ghi lên GCS `transcripts/<sid>.json` khi `PIPELINE=diarized` — `obeval` đọc thẳng file này.

Dùng cho giai đoạn 1 (5 video nghiệm thu) khi pipeline mới chưa bật trên server; KHÔNG chạy trên GPU prod dùng chung.
Chạy bằng Python của venv STT (cần faster-whisper, sherpa-onnx, onnxruntime, scikit-learn, soundfile):

  <SpeechToText>/.venv-dev/Scripts/python tools/stt_local.py <video.mp4|audio> <out.json> \
      --stt-repo D:/TeenCare/SpeechToText-diarized --models D:/TeenCare/stt-models

Thư mục --models cần: sortformer/ (sortformer_step.onnx, mel_fb.npy, window.npy — export bằng
tools/export_sortformer_onnx.py của repo STT), titanet/nemo_en_titanet_small.onnx, gipformer/, turbo/.
Biến môi trường của repo STT (DEVICE, DIAR_DEVICE, BATCH_SIZE...) vẫn ghi đè được.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
from pathlib import Path

EXTRA_KEYS = ("turns", "transcript_labeled", "roles", "session_flag", "pipeline", "timings")  # = app/worker.py


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("audio")
    ap.add_argument("out")
    ap.add_argument("--stt-repo", default=os.environ.get("STT_REPO", "D:/TeenCare/SpeechToText-diarized"))
    ap.add_argument("--models", default=os.environ.get("STT_MODELS", "D:/TeenCare/stt-models"))
    ap.add_argument("--session-id", help="Mặc định: tên file audio")
    ap.add_argument("--language", default="vi")
    ap.add_argument("--dll-dir", action="append", default=[],
                    help="Windows: thư mục chứa cublas64_12.dll / cudnn*.dll cho turbo chạy GPU (lặp được)")
    args = ap.parse_args()
    for d in args.dll_dir:  # CTranslate2 nạp cuBLAS/cuDNN qua PATH
        os.environ["PATH"] = d + os.pathsep + os.environ.get("PATH", "")
        if hasattr(os, "add_dll_directory"):
            os.add_dll_directory(d)

    m = Path(args.models)
    defaults = {
        "PIPELINE": "diarized",
        "MODEL_DIR": str(m / "turbo"),
        "SORTFORMER_MODEL": str(m / "sortformer"),
        "TITANET_MODEL": str(m / "titanet" / "nemo_en_titanet_small.onnx"),
        "GIPFORMER_DIR": str(m / "gipformer"),
        "PUNCT_FILL": "false",            # như cấu hình đã chốt trên server (capu tắt)
        "DIAR_DEVICE": "cpu",             # venv dev chỉ có onnxruntime CPU; kết quả như GPU, chậm hơn (~70 s / 30 phút)
        "TMP_DIR": tempfile.mkdtemp(prefix="stt-local-"),
        "CPU_THREADS": str(os.cpu_count() or 4),
    }
    for k, v in defaults.items():
        os.environ.setdefault(k, v)
    for k in ("MODEL_DIR", "SORTFORMER_MODEL", "TITANET_MODEL", "GIPFORMER_DIR"):
        if not Path(os.environ[k]).exists():
            print(f"Thiếu model {k}: {os.environ[k]}", file=sys.stderr)
            return 2
    sys.path.insert(0, str(Path(args.stt_repo).resolve()))

    from app.config import settings
    from app.pipeline.engine import build_pipeline

    t = time.time()
    res = build_pipeline(settings).transcribe(args.audio, args.language)
    payload = {"session_id": args.session_id or Path(args.audio).stem, "transcript": res["transcript"],
               "segments": res["segments"], "duration_sec": res["duration_sec"]}
    payload.update({k: res[k] for k in EXTRA_KEYS if k in res})
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"out": args.out, "duration_sec": res["duration_sec"], "total_sec": round(time.time() - t, 1),
                      "roles": res.get("roles"), "session_flag": res.get("session_flag"),
                      "segments": len(res["segments"]), "timings": res.get("timings")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
