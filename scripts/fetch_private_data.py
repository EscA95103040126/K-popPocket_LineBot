"""Download the private Play Zone CSVs from a private Hugging Face Dataset repo.

These CSVs are not committed to git (see .gitignore). The Space runs this before
gunicorn and CI runs it before pytest; both need the HF_TOKEN secret (read access
to the dataset). Without HF_TOKEN it does nothing, so local copies are used as-is.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import requests

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPO = "EscA95103040126/kpop-agent-private-data"
# Paths are the same in the dataset repo and in this project.
PRIVATE_FILES = (
    "data/play_zone/bias_radar_members.csv",
    "data/play_zone/daily_fancam.csv",
    "data/play_zone/daily_mv.csv",
    "data/play_zone/daily_stage.csv",
    "data/play_zone/member_quiz.csv",
)
TIMEOUT_SECONDS = 30


def fetch_private_data(repo: str, token: str, root: Path = PROJECT_ROOT) -> None:
    session = requests.Session()
    session.headers["Authorization"] = f"Bearer {token}"
    for relative_path in PRIVATE_FILES:
        url = f"https://huggingface.co/datasets/{repo}/resolve/main/{relative_path}"
        response = session.get(url, timeout=TIMEOUT_SECONDS)
        response.raise_for_status()
        target = root / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        # Write then rename, so a failed download never leaves half a CSV behind.
        partial = target.with_suffix(target.suffix + ".part")
        partial.write_bytes(response.content)
        partial.replace(target)
        print(f"Fetched {relative_path} ({len(response.content)} bytes)")


def main() -> int:
    token = os.environ.get("HF_TOKEN", "").strip()
    if not token:
        print("HF_TOKEN is not set; using local private CSVs as-is.")
        return 0
    repo = os.environ.get("PRIVATE_DATA_REPO", "").strip() or DEFAULT_REPO
    try:
        fetch_private_data(repo, token)
    except requests.RequestException as error:
        # Status and URL only: the token is in the request headers, never in the message.
        print(f"Failed to fetch private data from {repo}: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
