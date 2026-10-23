from __future__ import annotations

import csv
from collections.abc import Callable
from pathlib import Path


def _bias_radar_row_is_usable(row: dict[str, str]) -> bool:
    required_fields = ("id", "artist", "member", "gender_group", "group_type", "url")
    if any(not row.get(field, "").strip() for field in required_fields):
        return False
    filled_tag_fields = sum(
        1
        for field in ("appearance", "position", "vibe", "relationship")
        if row.get(field, "").strip()
    )
    return filled_tag_fields >= 3


def _daily_kpop_row_is_usable(row: dict[str, str]) -> bool:
    return bool(row.get("title", "").strip() and row.get("url", "").strip())


def _daily_kpop_csv_filename(category: str) -> str:
    if category == "直拍":
        return "daily_fancam.csv"
    if category == "經典舞台":
        return "daily_stage.csv"
    return "daily_mv.csv"


def daily_kpop_csv_label(category: str) -> str:
    return f"data/play_zone/{_daily_kpop_csv_filename(category)}"


class PlayZoneCatalog:
    """Reads the Play Zone CSV datasets under base_dir, re-reading a file only when it changes."""

    def __init__(self, base_dir: Path) -> None:
        self.base_dir = base_dir
        self.csv_row_cache: dict[Path, tuple[tuple[int, int], list[dict[str, str]]]] = {}

    def load_cached_csv_rows(
        self,
        csv_path: Path,
        row_filter: Callable[[dict[str, str]], bool],
        row_mapper: Callable[[dict[str, str]], dict[str, str]] | None = None,
    ) -> list[dict[str, str]]:
        if not csv_path.exists():
            self.csv_row_cache.pop(csv_path, None)
            return []

        stat = csv_path.stat()
        cache_key = (stat.st_mtime_ns, stat.st_size)
        cached = self.csv_row_cache.get(csv_path)
        if cached and cached[0] == cache_key:
            return [dict(row) for row in cached[1]]

        with csv_path.open(newline="", encoding="utf-8") as file:
            rows = [
                row_mapper(row) if row_mapper else dict(row)
                for row in csv.DictReader(file)
                if row_filter(row)
            ]
        self.csv_row_cache[csv_path] = (cache_key, rows)
        return [dict(row) for row in rows]

    def load_bias_radar_members(self) -> list[dict[str, str]]:
        csv_path = self.base_dir / "data" / "play_zone" / "bias_radar_members.csv"
        return self.load_cached_csv_rows(csv_path, _bias_radar_row_is_usable)

    def load_daily_kpop_rows(self, category: str) -> list[dict[str, str]]:
        csv_path = self.base_dir / "data" / "play_zone" / _daily_kpop_csv_filename(category)
        return self.load_cached_csv_rows(csv_path, _daily_kpop_row_is_usable)
