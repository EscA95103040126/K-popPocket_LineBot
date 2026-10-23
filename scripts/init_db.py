from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.tools.chart_db import ChartHistoryRepository


def main() -> None:
    repo = ChartHistoryRepository()
    repo.init_db()
    print(f"Initialized database: {repo.db_path}")


if __name__ == "__main__":
    main()
