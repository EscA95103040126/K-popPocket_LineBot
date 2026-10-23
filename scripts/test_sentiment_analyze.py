import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.tools.sentiment import analyze_sentiment_from_csv


def main():
    for artist in ["aespa", "IVE", "NewJeans", "Unknown"]:
        result = analyze_sentiment_from_csv(artist)
        print(f"\n=== {artist} ===")
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
