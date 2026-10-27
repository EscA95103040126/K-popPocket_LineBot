"""AI 入坑 v4：有來源的成員特質，只用來寫推薦理由，不影響排序。

證據表由 scripts/build_member_evidence.py 從 Grok 批次產生，只收 supported 的主張。
成員沒有某項證據不代表他沒有這個特質，只代表理由不能這樣寫。
"""

from __future__ import annotations

import csv
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

MEMBER_EVIDENCE_PATH = Path("data") / "curator" / "member_evidence.csv"
EVIDENCE_FIELDS = ["evidence_id", "member_id", "facet", "perspective", "value", "source_count"]
EVIDENCE_PER_MEMBER = 3

FACET_CUES = {
    "contrast": ("反差", "落差", "變了一個人", "像變了", "台上台下", "臺上臺下", "兩面"),
    "variety": ("綜藝", "搞笑", "好笑", "幽默", "有梗", "主持", "實境", "很會說話"),
    "vocal": ("聲線", "聲音", "唱腔", "嗓音", "歌聲", "高音", "音色", "唱功", "vocal"),
    "performance": ("舞台", "舞臺", "舞蹈", "跳舞", "表演", "直拍", "饒舌", "rap", "dance"),
    "offstage_public": ("私下", "平常", "日常", "本人"),
    "vibe": ("氣質", "氛圍", "個性", "性格", "溫柔", "可愛", "清冷", "高冷", "開朗", "穩重"),
}
FACET_LABELS = {
    "contrast": "反差（台上台下或外表與個性的落差）",
    "variety": "綜藝感",
    "vocal": "歌聲",
    "performance": "舞台表現",
    "offstage_public": "私下的樣子",
    "vibe": "個性氣質",
}
# 粉絲觀感彙整最貼近「大家怎麼看這個人」；事件紀錄（主持過什麼）放最後。
PERSPECTIVE_ORDER = {"fan_perception": 0, "press": 1, "other_person": 2, "event_record": 3}


def load_member_evidence(base_dir: Path) -> dict[str, list[dict[str, str]]]:
    path = base_dir / MEMBER_EVIDENCE_PATH
    try:
        with path.open(encoding="utf-8-sig", newline="") as f:
            rows = list(csv.DictReader(f))
    except OSError:
        logger.info("No member evidence at %s; reasons use profiles only.", path)
        return {}
    evidence: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        if row.get("member_id") and row.get("value"):
            evidence.setdefault(row["member_id"], []).append(row)
    return evidence


def query_facets(query: str) -> list[str]:
    text = query.casefold()
    return [facet for facet, cues in FACET_CUES.items() if any(cue in text for cue in cues)]


def pick_member_evidence(
    rows: list[dict[str, str]], query: str, limit: int = EVIDENCE_PER_MEMBER
) -> list[dict[str, str]]:
    """使用者問到的面向優先，其次是粉絲觀感、來源多的主張。"""

    facets = query_facets(query)

    def sort_key(row: dict[str, str]) -> tuple[int, int, int]:
        facet = row.get("facet", "")
        try:
            sources = int(row.get("source_count") or 1)
        except ValueError:
            sources = 1
        return (
            facets.index(facet) if facet in facets else len(facets),
            PERSPECTIVE_ORDER.get(row.get("perspective", ""), len(PERSPECTIVE_ORDER)),
            -sources,
        )

    return sorted(rows, key=sort_key)[:limit]
