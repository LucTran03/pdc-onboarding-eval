"""Đường dẫn và tham số mặc định. Đổi bằng biến môi trường OBEVAL_* khi chạy ở máy khác."""
from __future__ import annotations

import os
from pathlib import Path

TOOL_DIR = Path(__file__).resolve().parent.parent
# Repo riêng: prompt/ nằm cạnh obeval/. Workspace anh Lực: prompt/ nằm ở thư mục cha của tool/.
_PROMPT_CANDIDATES = [Path(os.environ["OBEVAL_PROMPT_DIR"])] if os.environ.get("OBEVAL_PROMPT_DIR") else []
_PROMPT_CANDIDATES += [TOOL_DIR / "prompt", TOOL_DIR.parent / "prompt"]
PROMPT_DIR = next((p for p in _PROMPT_CANDIDATES if (p / "criteria.json").exists()), _PROMPT_CANDIDATES[0])
SYSTEM_PROMPT_PATH = PROMPT_DIR / "system_prompt.md"
CRITERIA_PATH = PROMPT_DIR / "criteria.json"
OUTPUT_SCHEMA_PATH = PROMPT_DIR / "output_schema.json"

# Kịch bản và kết quả thật nằm NGOÀI git (dữ liệu nội bộ / dữ liệu trẻ em).
# Mặc định: D:/teencare-data/pdc-onboarding nếu có (máy anh Lực), không thì ./data cạnh repo (đã .gitignore).
_LEGACY_DATA = Path("D:/teencare-data/pdc-onboarding")
DATA_ROOT = Path(os.environ.get("OBEVAL_DATA_ROOT") or (_LEGACY_DATA if _LEGACY_DATA.exists() else TOOL_DIR / "data"))
SCRIPT_PATH = Path(os.environ.get("OBEVAL_SCRIPT", str(DATA_ROOT / "raw" / "090426_SEC_Script_Onboarding.txt")))
OUT_ROOT = Path(os.environ.get("OBEVAL_OUT_ROOT", str(DATA_ROOT / "out")))

# Vertex AI của công ty. Credential: GOOGLE_APPLICATION_CREDENTIALS (service account) hoặc
# `gcloud auth application-default login`. OBEVAL_GCP_KEY chỉ là đường dẫn — tool không mở file key.
GCP_PROJECT = os.environ.get("OBEVAL_GCP_PROJECT", "tcservices2027")
GCP_LOCATION = os.environ.get("OBEVAL_GCP_LOCATION", "us-central1")
_LEGACY_KEY = "D:/teencare-data/" + "gcp-key" + ".json"
GCP_KEY_PATH = os.environ.get("OBEVAL_GCP_KEY") or (_LEGACY_KEY if os.path.exists(_LEGACY_KEY) else "")

DEFAULT_MODEL = os.environ.get("OBEVAL_MODEL", "gemini-2.5-pro")
DEFAULT_THINKING_BUDGET = int(os.environ.get("OBEVAL_THINKING", "16384"))
DEFAULT_MAX_OUTPUT_TOKENS = 65535
# Số lần chấm mỗi ca rồi lấy đa số (ensemble.py). Đo 09/10: 1 lần chạy dao động 76–89% trùng đáp án.
DEFAULT_RUNS = int(os.environ.get("OBEVAL_RUNS", "3"))
# Bộ nhiều lần cần đa dạng thật: temperature mặc định của Gemini 2.5 + seed khác nhau mỗi lần.
ENSEMBLE_TEMPERATURE = float(os.environ.get("OBEVAL_ENSEMBLE_TEMPERATURE", "1.0"))

# Ngưỡng — PDC chưa chốt; đầu ra v3.0 gợi ý 85%.
GOOD_THRESHOLD = float(os.environ.get("OBEVAL_GOOD_THRESHOLD", "0.85"))
NE_RATIO_INSUFFICIENT = float(os.environ.get("OBEVAL_NE_RATIO", "0.30"))

# Cảnh báo transcript bất thường (có thể gộp nhầm nhiều buổi).
MAX_TRANSCRIPT_TOKENS_WARN = 100_000

# Giá Vertex (USD / 1 triệu token), mức ≤ 200k token prompt. Thinking tính như output.
PRICING = {
    "gemini-2.5-pro": {"input": 1.25, "output": 10.0},
    "gemini-2.5-flash": {"input": 0.30, "output": 2.50},
}
