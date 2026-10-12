"""Điểm vào: `python run.py <lệnh> ...` từ bất kỳ thư mục nào (xem README.md)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from obeval.cli import main  # noqa: E402

sys.exit(main())
