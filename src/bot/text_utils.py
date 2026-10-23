from __future__ import annotations

import re
import unicodedata


def safe_float(value: object) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def bias_radar_tag_text(raw_value: str) -> str:
    return " / ".join(tag.strip() for tag in raw_value.split("|") if tag.strip())


def display_member_name(member: str) -> str:
    cleaned = member.strip()
    special_names = {"RM", "V", "DK", "D.O.", "I.N", "THE8"}
    if cleaned.upper() in special_names:
        return cleaned.upper()
    if cleaned and cleaned == cleaned.upper():
        return cleaned.title()
    return cleaned


def contains_lookup_name(message: str, value: str) -> bool:
    normalized_message = _lookup_text(message)
    normalized_value = _lookup_text(value)
    if not normalized_message or not normalized_value:
        return False
    pattern = re.escape(normalized_value).replace(r"\ ", r"\s+")
    return re.search(rf"(?<![a-z0-9]){pattern}(?![a-z0-9])", normalized_message) is not None


def same_lookup_name(left: str, right: str) -> bool:
    return _lookup_text(left) == _lookup_text(right)


def _lookup_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value).casefold()
    without_marks = "".join(
        character for character in normalized if not unicodedata.combining(character)
    )
    return re.sub(r"\s+", " ", without_marks.strip())


def join_nonempty_blocks(*blocks: str) -> str:
    return "\n\n".join(block.strip() for block in blocks if block and block.strip())


def split_bias_radar_tags(raw_value: str) -> set[str]:
    return {tag.strip() for tag in raw_value.split("|") if tag.strip()}
