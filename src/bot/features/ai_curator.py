from __future__ import annotations

import json
import logging
import random
import re
import unicodedata
from collections.abc import Callable
from typing import TYPE_CHECKING

from src.bot.dispatcher import MessageContext
from src.bot.flex_common import selection_page_flex_contents
from src.bot.member_evidence import FACET_LABELS, pick_member_evidence, query_facets
from src.bot.reply import Reply
from src.bot.semantic_index import query_gender
from src.bot.text_utils import (
    bias_radar_tag_text,
    contains_lookup_name,
    display_member_name,
    join_nonempty_blocks,
    same_lookup_name,
    split_bias_radar_tags,
)
from src.utils.response_formatter import fit_line_text

if TYPE_CHECKING:
    from src.bot.catalog import PlayZoneCatalog
    from src.bot.llm import GeminiTextClient
    from src.bot.semantic_index import SemanticMemberRanker
    from src.bot.sessions import SessionStore

logger = logging.getLogger(__name__)


AI_CURATOR_REASON_CONTEXT_TTL_SECONDS = 60 * 30
AI_CURATOR_REASON_CONTEXT_NAMESPACE = "ai_curator_reason"
# After the 「AI 入坑」 entry asks for a preference, free text counts as one even when it
# names none of the keywords below, until a fixed command or the TTL ends that mode.
AI_CURATOR_AWAITING_NAMESPACE = "ai_curator_awaiting"
AI_CURATOR_AWAITING_TTL_SECONDS = 60 * 10
# Last-resort routing: free text no other feature claimed that still reads like a
# preference (「我喜歡比較年輕的，唱歌比較好的那種」) goes to AI 入坑, not the help text.
AI_CURATOR_FREE_TEXT_CUES = (
    "喜歡",
    "想找",
    "想看",
    "想追",
    "想聽",
    "想認識",
    "推薦",
    "推坑",
    "入坑",
    "有沒有",
    "求",
    "適合",
    "那種",
    "那樣",
    "類似",
)
AI_CURATOR_FREE_TEXT_MIN_CHARS = 6
AI_CURATOR_ANSWER_MEMBERS = 3
AI_CURATOR_REASON_MIN_CHINESE_CHARS = 6
AI_CURATOR_REASON_MAX_CHARS = 60
# 追問的 🔎／💫 兩句可以帶成員名和兩個特點，比主回覆的一句理由長。
AI_CURATOR_FOLLOWUP_SENTENCE_MAX_CHARS = 80
AI_CURATOR_ENTRY_TRIGGERS = {
    "我的雷達",
    "雷達",
    "ai入坑",
    "ai入坑指南",
    "入坑指南",
    "k-pop雷達",
    "kpop雷達",
    "ai策展人",
    "aik-pop策展人",
    "aikpop策展人",
    "ai k-pop策展人",
    "k-pop策展人",
    "kpop策展人",
    "策展人",
}
AI_CURATOR_PROFILE_FIELDS = ("appearance", "position", "vibe", "relationship", "persona")
AI_CURATOR_PROFILE_VOCAB: dict[str, tuple[str, ...]] = {
    "appearance": ("貓咪", "狗狗", "小兔", "狐狸", "小鹿"),
    "position": ("Vocal", "Dance", "Rap", "Visual", "All-rounder"),
    "vibe": ("冷感", "甜系", "霸氣", "反差", "清冷"),
    "relationship": ("戀愛感", "神性", "朋友感", "白月光感", "舞台支配感"),
    "persona": (
        "姐系",
        "忙內",
        "鄰家",
        "氛圍",
        "元氣",
        "痞帥",
        "知性",
        "治癒",
        "綜藝擔",
        "性感",
        "憂鬱感",
        "陽光",
        "王子",
        "野性",
    ),
}


def _build_ai_curator_entry_flex_contents() -> dict:
    return selection_page_flex_contents(
        title="AI 入坑",
        subtitle="偏好推薦",
        description="直接告訴我你的偏好，我會根據本命雷達、每日推薦與藝人資料幫你排入坑路線。",
        accent_color="#6F5BA7",
        items=[
            {
                "icon": "🌙",
                "title": "清冷女團入坑",
                "description": "適合喜歡清冷感、舞台視覺和概念感的人。",
                "text": "我想入坑清冷感、舞台強的女團",
            },
            {
                "icon": "🎤",
                "title": "Vocal 取向推薦",
                "description": "適合想先看唱功、現場和直拍的人。",
                "text": "幫我推薦 vocal 強、現場穩的 K-pop",
            },
            {
                "icon": "🔥",
                "title": "霸氣舞台路線",
                "description": "適合偏好 rap、dance 和舞台支配感的人。",
                "text": "我喜歡霸氣舞台、rap 和 dance，推薦我入坑路線",
            },
            {
                "icon": "💿",
                "title": "自由描述偏好",
                "description": "也可以直接輸入：我喜歡...，幫我推薦。",
                "text": "我喜歡甜系、白月光感和好聽 MV，幫我推薦",
            },
        ],
    )


def _build_ai_curator_followup_flex_contents(
    artist: str | None = None,
    recommended_members: list[dict[str, str]] | None = None,
) -> dict:
    reason_buttons = []
    seen_members = set()
    for recommendation in recommended_members or []:
        member = recommendation.get("member", "").strip()
        if not member:
            continue
        display_member = display_member_name(member)
        lookup_key = display_member.casefold()
        if lookup_key in seen_members:
            continue
        seen_members.add(lookup_key)
        action_text = f"為什麼推薦 {display_member}？"
        reason_buttons.append(_ai_curator_button(action_text, action_text))
        if len(reason_buttons) >= 3:
            break

    buttons = [
        *reason_buttons,
        _ai_curator_button("本命雷達", "本命雷達測驗"),
        _ai_curator_button("抽 MV", "每日 MV"),
        _ai_curator_button("抽直拍", "每日直拍"),
    ]
    return {
        "type": "bubble",
        "size": "kilo",
        "header": {
            "type": "box",
            "layout": "vertical",
            "backgroundColor": "#6F5BA7",
            "paddingAll": "14px",
            "contents": [
                {
                    "type": "text",
                    "text": "接下來想看？",
                    "size": "md",
                    "weight": "bold",
                    "color": "#FFFFFF",
                },
            ],
        },
        "body": {
            "type": "box",
            "layout": "vertical",
            "backgroundColor": "#F7F3FF",
            "paddingAll": "14px",
            "spacing": "sm",
            "contents": buttons,
        },
    }


def _ai_curator_button(label: str, text: str) -> dict:
    return {
        "type": "button",
        "style": "secondary",
        "height": "sm",
        "action": {
            "type": "message",
            "label": label,
            "text": text,
        },
    }


def is_ai_curator_entry_request(message: str) -> bool:
    normalized = message.strip().casefold().replace(" ", "")
    return normalized in AI_CURATOR_ENTRY_TRIGGERS


def is_ai_curator_reason_followup(message: str) -> bool:
    compact = unicodedata.normalize("NFKC", message).strip().casefold().replace(" ", "")
    if not compact:
        return False
    return (
        "為什麼推薦" in compact
        or "推薦理由" in compact
        or "為何推薦" in compact
        or ("推薦" in compact and "理由" in compact)
    )


def ai_curator_entry_reply(context: MessageContext) -> Reply:
    return Reply(
        report="AI 入坑",
        flex=_build_ai_curator_entry_flex_contents(),
        alt_text="AI 入坑",
        fallback_text="請直接輸入你的 K-pop 偏好，例如：我想入坑清冷感、舞台強的女團。",
    )


def _clean_ai_curator_query(message: str) -> str:
    cleaned = message.strip()
    for prefix in (
        "AI入坑:",
        "ai入坑:",
        "入坑指南:",
        "AI策展:",
        "ai策展:",
        "策展:",
        "雷達:",
        "推薦:",
    ):
        if cleaned.startswith(prefix):
            return cleaned.removeprefix(prefix).strip() or "幫我推薦 K-pop 入坑路線"
    return cleaned


def _ai_curator_profile_has_signal(profile: dict) -> bool:
    if profile.get("artists"):
        return True
    return any(profile.get(field) for field in AI_CURATOR_PROFILE_FIELDS)


def _build_ai_curator_profile_prompt(query: str) -> str:
    vocab_lines = "\n".join(
        f"- {field}: {', '.join(labels)}" for field, labels in AI_CURATOR_PROFILE_VOCAB.items()
    )
    return f"""你是 K-pop 偏好解析器。請把使用者的自然語言需求對應到下方「允許的標籤」，輸出 JSON。
規則：
- 只能使用下方列出的標籤，禁止自創新標籤；語意接近就對應過去（例如「姐系/御姐/成熟」對應 persona 的「姐系」）。
- 每個欄位可給 0 到多個標籤；完全沒提到就給空陣列。
- gender 只能是 "male"、"female" 或 null。
- 只輸出 JSON，不要任何說明文字。

允許的標籤：
{vocab_lines}

輸出格式：
{{"gender": null, "appearance": [], "position": [], "vibe": [], "relationship": [], "persona": []}}

使用者需求：
{query}"""


def _parse_ai_curator_profile_json(text: str) -> dict | None:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:]
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end == -1 or end < start:
        return None
    try:
        raw = json.loads(cleaned[start : end + 1])
    except (ValueError, TypeError):
        return None
    if not isinstance(raw, dict):
        return None

    gender = raw.get("gender")
    if gender not in ("male", "female"):
        gender = None
    profile: dict[str, set[str] | str | None] = {"gender": gender}
    for field, allowed in AI_CURATOR_PROFILE_VOCAB.items():
        values = raw.get(field) or []
        if isinstance(values, str):
            values = [values]
        allowed_set = set(allowed)
        profile[field] = {value for value in values if value in allowed_set}
    return profile


def _compact_ai_curator_text(text: str) -> str:
    return unicodedata.normalize("NFKC", text).casefold().replace(" ", "")


def _keyword_matches(compact_query: str, mapping: dict[str, tuple[str, ...]]) -> set[str]:
    return {
        label
        for label, keywords in mapping.items()
        if any(keyword.casefold().replace(" ", "") in compact_query for keyword in keywords)
    }


def _prioritize_members_with_mv(
    members: list[dict[str, str]],
    mv_artists: set[str],
) -> list[dict[str, str]]:
    with_mv = [member for member in members if member.get("artist", "").strip() in mv_artists]
    without_mv = [
        member for member in members if member.get("artist", "").strip() not in mv_artists
    ]
    return with_mv + without_mv


def _ai_curator_recommended_members(
    member_candidates: list[dict[str, str]],
) -> list[dict[str, str]]:
    recommendations = []
    seen_members = set()
    for member in member_candidates:
        artist_name = member.get("artist", "").strip()
        member_name = member.get("member", "").strip()
        if not artist_name or not member_name:
            continue
        lookup_key = (artist_name.casefold(), member_name.casefold())
        if lookup_key in seen_members:
            continue
        seen_members.add(lookup_key)
        recommendations.append({"artist": artist_name, "member": member_name})
        if len(recommendations) >= 3:
            break
    return recommendations


def _ai_curator_recommended_artists(member_candidates: list[dict[str, str]]) -> list[str]:
    artists: list[str] = []
    for member in member_candidates:
        artist = member.get("artist", "").strip()
        if artist and artist not in artists:
            artists.append(artist)
    return artists


def _daily_artist_looks_female(artist: str) -> bool:
    upper_artist = artist.upper()
    female_markers = {
        "AESPA",
        "IVE",
        "NMIXX",
        "ILLIT",
        "BABYMONSTER",
        "BLACKPINK",
        "TWICE",
        "KISS OF LIFE",
        "LE SSERAFIM",
        "QWER",
        "NEWJEANS",
    }
    return any(marker in upper_artist for marker in female_markers)


def _ai_curator_artist_candidates(
    member_candidates: list[dict[str, str]],
    daily_items: list[dict[str, str]],
) -> list[str]:
    artists: list[str] = []
    for member in member_candidates:
        artists.append(member.get("artist", "").strip())
    for item in daily_items:
        artists.append(item.get("artist", "").strip())
    return list(dict.fromkeys(artist for artist in artists if artist))


def _ai_curator_member_line(member: dict[str, str], notes: dict[str, str]) -> str:
    name = f"- {member.get('artist')} {member.get('member')}"
    if note := notes.get(member.get("id", "")):
        # Only the curated note: the v1 tags (e.g. position=Vocal) led Gemini to call
        # members who are not main vocalists 「主唱」.
        return f"{name}：{note}"
    # v1 fallback has no curated notes, so the tag table is all there is.
    return (
        f"{name}: position={member.get('position')}; vibe={member.get('vibe')}; "
        f"relationship={member.get('relationship')}; persona={member.get('persona')}"
    )


def _build_ai_curator_prompt(query: str, context: dict) -> str:
    """Ask Gemini for one reason per recommended member; the reply layout stays in code.

    Free-form answers drifted (dropped group names, MV-only picks, invented commands),
    so Gemini now fills the reasons into the same layout as the fallback answer.
    """

    notes = context.get("member_notes") or {}
    evidence = context.get("member_evidence") or {}
    members = context["member_candidates"][:AI_CURATOR_ANSWER_MEMBERS]
    asked = query_facets(query)
    member_lines = []
    for index, member in enumerate(members, start=1):
        line = f"{index}. " + _ai_curator_member_line(member, notes).removeprefix("- ")
        rows = evidence.get(member.get("id", ""), [])
        if rows:
            line += "\n   有來源的特質：" + "；".join(row["value"] for row in rows)
        # 只說「不要捏造」擋不住 Gemini 照抄使用者的話，逐人點名缺的面向才有用。
        if missing := [f for f in asked if f not in {row.get("facet") for row in rows}]:
            line += (
                "\n   資料沒寫他的"
                + "、".join(FACET_LABELS[f] for f in missing)
                + "，理由不要提這些。"
            )
        member_lines.append(line)
    return f"""你是 K-pop 入坑指南。推薦系統已依使用者的偏好排好下面 {len(members)} 位成員，
請為每位成員寫一句繁體中文（台灣用語）的推薦理由。

規則：
- 每句 15 到 30 字（短一點，LINE 上才好讀），說明這位成員為什麼符合使用者的偏好，語氣親切可愛。
- 只能根據成員資料寫；定位（主唱、主舞、隊長等）和特質資料沒寫就不要提，不要捏造。
- 「有來源的特質」是整理過的粉絲觀感或報導，和偏好有關時優先用它；粉絲觀感要寫成「粉絲常說…」，不要寫成事實。
- 使用者要的特質（例如反差、搞笑、聲線）資料裡沒寫，就不要說這位成員有，改說他其他值得認識的地方。
- 不要寫成員名字或團名（版面會另外顯示），不要加網址、表情符號或編號。
- 只輸出 JSON 字串陣列，順序和成員相同，例如 ["理由一", "理由二", "理由三"]。

使用者偏好：
{query}

成員：
{chr(10).join(member_lines)}
"""


def _parse_ai_curator_reasons(
    text: str,
    count: int,
    max_chars: int = AI_CURATOR_REASON_MAX_CHARS,
) -> list[str | None]:
    """One cleaned reason per member, None where Gemini's line is unusable."""

    match = re.search(r"\[.*\]", text, re.DOTALL)
    try:
        values = json.loads(match.group(0)) if match else []
    except ValueError:
        values = []
    if not isinstance(values, list):
        values = []
    reasons: list[str | None] = []
    for index in range(count):
        value = values[index] if index < len(values) else None
        reasons.append(
            _clean_ai_curator_reason(value, max_chars) if isinstance(value, str) else None
        )
    return reasons


def _clean_ai_curator_reason(
    value: str,
    max_chars: int = AI_CURATOR_REASON_MAX_CHARS,
) -> str | None:
    reason = re.sub(r"^\s*(?:\d+[.、．)]\s*)", "", " ".join(value.split())).strip()
    # 版面的 emoji 由程式加，Gemini 自己帶的去掉，免得重複。
    reason = reason.lstrip("✨🔎💫🎬📰 ").strip()
    if not reason or "http" in reason.casefold() or len(reason) > max_chars:
        return None
    if _chinese_char_count(reason) < AI_CURATOR_REASON_MIN_CHINESE_CHARS:
        # Too short to say anything, or not Chinese at all.
        return None
    return reason if reason[-1] in "。！？!?～~" else f"{reason}。"


def _llm_error(error: Exception) -> str:
    """Status code or exception type only: requests puts the API key (?key=...) in the URL
    of its error messages, so the message itself must never reach the logs."""
    response = getattr(error, "response", None)
    status = getattr(response, "status_code", None)
    return f"HTTP {status}" if status else type(error).__name__


def _chinese_char_count(text: str) -> int:
    return len(re.findall(r"[一-鿿]", text))


def _fallback_ai_curator_answer(query: str, context: dict) -> str:
    return _render_ai_curator_answer(query, context, reasons=None)


def _render_ai_curator_answer(
    query: str,
    context: dict,
    reasons: list[str | None] | None,
) -> str:
    member_candidates = context.get("member_candidates", [])
    daily_items = context.get("daily_items", [])
    lines = [
        "🧭 AI 入坑",
        f"根據你說的「{query}」，我會這樣排：",
    ]
    if member_candidates:
        evidence = context.get("member_evidence") or {}
        for index, member in enumerate(member_candidates[:AI_CURATOR_ANSWER_MEMBERS], start=1):
            reason = reasons[index - 1] if reasons and index <= len(reasons) else None
            lines.append(
                f"{index}. {member['artist']} {member['member']}："
                + (
                    reason
                    or _evidence_fallback_reason(evidence.get(member.get("id", ""), []), query)
                    or f"{member.get('vibe', '風格鮮明')}，適合先看本命雷達。"
                )
            )
    elif daily_items:
        for index, item in enumerate(daily_items[:3], start=1):
            lines.append(f"{index}. {item['artist']}《{item['title']}》：適合先聽 MV 入坑。")
    else:
        lines.append("目前資料還不夠，建議先從本命雷達測驗或每日一首開始。")

    if daily_items:
        item = daily_items[0]
        lines.append(f"今日入口：先看 {item['artist']}《{item['title']}》")
        if item.get("url"):
            lines.append(item["url"])
    return fit_line_text("\n".join(lines), limit=900)


def _evidence_fallback_reason(rows: list[dict[str, str]], query: str) -> str | None:
    """沒有 Gemini 時，直接用一條粉絲觀感當理由；它本來就寫成「粉絲常說…」的口吻。

    只用使用者問到的面向（沒問特定面向時用氣質），問聲線卻回「綜藝很好笑」會答非所問。
    """

    facets = query_facets(query) or ["vibe"]
    for row in rows:
        if row.get("perspective") == "fan_perception" and row.get("facet") in facets:
            value = row["value"].rstrip("。")
            return f"{value}。"
    return None


def _ai_curator_reason_member_is_usable(row: dict[str, str]) -> bool:
    return (
        bool(row.get("artist", "").strip())
        and bool(row.get("member", "").strip())
        and any(
            row.get(field, "").strip()
            for field in ("appearance", "position", "vibe", "relationship")
        )
    )


def _ai_curator_reason_sentences(member_row: dict[str, str], member: str) -> list[str]:
    appearance = _natural_bias_tag_text(member_row.get("appearance", ""))
    position = _natural_position_tag_text(member_row.get("position", ""))
    vibe = _natural_bias_tag_text(member_row.get("vibe", ""))
    relationship = _natural_bias_tag_text(member_row.get("relationship", ""))

    sentences = []
    if appearance and vibe:
        sentences.append(
            f"🔎 如果你吃{appearance}那種第一眼的清透感，"
            f"{member} 會很容易先對上；再加上{vibe}的反差，會讓人想多看幾支舞台。"
        )
    elif appearance:
        sentences.append(f"🔎 如果你吃{appearance}那種第一眼的清透感，{member} 會很容易先對上。")
    elif vibe:
        sentences.append(f"🔎 {vibe}這種氣場很適合當入坑入口，第一支舞台就能先抓感覺。")

    if relationship and position:
        sentences.append(
            f"💫 {relationship}的距離感很適合慢慢被圈進去，"
            f"入門可以先看能感受到{position}魅力的直拍。"
        )
    elif relationship:
        sentences.append(f"💫 {relationship}的距離感很適合慢慢被圈進去。")
    elif position:
        sentences.append(f"💫 入門可以先看能感受到{position}魅力的直拍。")
    return sentences


def _natural_bias_tag_text(raw_value: str) -> str:
    return "、".join(tag.strip() for tag in raw_value.split("|") if tag.strip())


def _natural_position_tag_text(raw_value: str) -> str:
    labels = []
    mapping = {
        "vocal": "聲線",
        "dance": "舞台動作",
        "rap": "rap 節奏感",
        "visual": "鏡頭感",
        "all-rounder": "全方位感",
        "allrounder": "全方位感",
    }
    for tag in (part.strip() for part in raw_value.split("|") if part.strip()):
        label = mapping.get(tag.casefold(), tag)
        if label not in labels:
            labels.append(label)
    return _join_chinese_list(labels)


def _join_chinese_list(values: list[str]) -> str:
    if len(values) <= 1:
        return values[0] if values else ""
    if len(values) == 2:
        return "和".join(values)
    return "、".join(values[:-1]) + "和" + values[-1]


def _parse_ai_curator_reason_sentences(text: str) -> list[str] | None:
    """Gemini 寫的 🔎、💫 兩句；任一句不能用就整段改用本地版本，不和本地句子混著拼。"""

    sentences = _parse_ai_curator_reasons(text, 2, AI_CURATOR_FOLLOWUP_SENTENCE_MAX_CHARS)
    if any(sentence is None for sentence in sentences):
        return None
    return [f"🔎 {sentences[0]}", f"💫 {sentences[1]}"]


def _format_fancam_link(row: dict[str, str], prefix: str) -> str:
    artist = row.get("artist", "").strip()
    member = display_member_name(row.get("member", ""))
    title = row.get("title", "").strip()
    url = row.get("url", "").strip()
    return f"{prefix}{artist} {member} - {title}\n{url}"


def _format_mv_link(row: dict[str, str], prefix: str) -> str:
    artist = row.get("artist", "").strip()
    title = row.get("title", "").strip()
    url = row.get("url", "").strip()
    return f"{prefix}{artist} - {title}\n{url}"


def _ai_curator_artist_summary_text(summary: dict[str, str] | None) -> str:
    if not summary:
        return ""
    artist = summary.get("artist", "").strip()
    if summary.get("insight"):
        return f"📰 補充團體近況：{artist} 近期重點是「{summary['insight']}」。"

    chart = _parse_ai_curator_summary_pairs(summary.get("chart", ""))
    best_rank = chart.get("best_rank")
    trend = chart.get("trend")
    if best_rank and best_rank != "NA":
        if trend and trend != "NA":
            return f"📰 補充團體近況：{artist} 近期榜單最好名次是第 {best_rank} 名，趨勢是{trend}。"
        return f"📰 補充團體近況：{artist} 近期榜單最好名次是第 {best_rank} 名。"
    return ""


def _parse_ai_curator_summary_pairs(raw_value: str) -> dict[str, str]:
    pairs = {}
    for part in raw_value.split(","):
        key, separator, value = part.partition("=")
        if separator:
            pairs[key.strip()] = value.strip()
    return pairs


class AiCuratorFeature:
    """AI 入坑: turns a free-text preference into member and MV recommendations."""

    def __init__(
        self,
        catalog: PlayZoneCatalog,
        llm: GeminiTextClient,
        rng: random.Random,
        sessions: SessionStore,
        is_fixed_command: Callable[[str], bool],
        semantic_ranker_loader: Callable[[], SemanticMemberRanker | None] | None = None,
    ) -> None:
        self.catalog = catalog
        self.llm = llm
        self.rng = rng
        self.sessions = sessions
        self.is_fixed_command = is_fixed_command
        # None, or a loader returning None, keeps the v1 tag ranking.
        self.semantic_ranker_loader = semantic_ranker_loader
        self._semantic_ranker: SemanticMemberRanker | None = None
        self._semantic_ranker_loaded = False

    def ai_curator_entry_reply(self, context: MessageContext) -> Reply:
        self._set_awaiting_preference(context.user_id)
        return ai_curator_entry_reply(context)

    def is_ai_curator_preference_message(self, context: MessageContext) -> bool:
        if self.is_ai_curator_preference_request(context.text):
            return True
        if not context.user_id or not self.sessions.get(
            AI_CURATOR_AWAITING_NAMESPACE, context.user_id
        ):
            return False
        if self.is_fixed_command(context.text):
            # The user moved on (menu button, quiz...), so stop reading free text as a
            # preference; otherwise a later quiz answer like 「女團」 would land here.
            self.sessions.delete(AI_CURATOR_AWAITING_NAMESPACE, context.user_id)
            return False
        return bool(context.text.strip()) and not is_ai_curator_reason_followup(context.text)

    def is_ai_curator_free_text_preference(self, context: MessageContext) -> bool:
        compact = _compact_ai_curator_text(context.text)
        if len(compact) < AI_CURATOR_FREE_TEXT_MIN_CHARS or self.is_fixed_command(context.text):
            return False
        if is_ai_curator_reason_followup(context.text):
            return False
        return any(cue in compact for cue in AI_CURATOR_FREE_TEXT_CUES)

    def _set_awaiting_preference(self, user_id: str | None) -> None:
        if user_id:
            self.sessions.set(
                AI_CURATOR_AWAITING_NAMESPACE,
                user_id,
                {"awaiting": True},
                AI_CURATOR_AWAITING_TTL_SECONDS,
            )

    def is_ai_curator_preference_request(self, message: str) -> bool:
        normalized = message.strip().casefold()
        compact = normalized.replace(" ", "")
        if not compact:
            return False
        if is_ai_curator_reason_followup(message) or self.is_fixed_command(message):
            return False
        if compact.startswith(("ai策展:", "策展:", "雷達:", "推薦:")):
            return True
        preference_actions = (
            "我想入坑",
            "幫我推薦",
            "有沒有推薦",
            "推薦我",
            "推薦",
            "推坑",
            "適合我",
            "適合",
            "入坑路線",
            "入坑",
            "想找",
            "找",
            "想追",
            "想看",
            "想認識",
            "哪個",
            "哪位",
            "誰",
            "求",
            "我喜歡",
            "喜歡",
        )
        preference_terms = (
            "女團",
            "男團",
            "小鹿",
            "鹿",
            "小兔",
            "兔",
            "貓",
            "狗",
            "狐",
            "vocal",
            "dance",
            "rap",
            "visual",
            "all-rounder",
            "清冷",
            "甜系",
            "霸氣",
            "反差",
            "冷感",
            "舞台",
            "直拍",
            "mv",
            "本命",
            "白月光感",
            "白月光",
            "守護感",
            "神性",
            "成員",
            "偶像",
            "愛豆",
            "idol",
            "主唱",
            "rapper",
            "舞擔",
            "門面",
            "全能",
            "現場",
            "聲線",
            "鏡頭",
        )
        member_target_terms = ("成員", "偶像", "愛豆", "idol", "本命")
        artist_mentioned = self._ai_curator_query_mentions_known_artist(compact)
        has_action = any(action in compact for action in preference_actions)
        has_preference_term = any(term in compact for term in preference_terms)
        has_member_target = any(term in compact for term in member_target_terms)
        persona_terms = (
            "姐系",
            "御姐",
            "忙內",
            "弟系",
            "maknae",
            "奶狗",
            "弟弟",
            "弟感",
            "鄰家",
            "邻家",
            "氛圍",
            "氛围",
            "元氣",
            "元气",
            "痞帥",
            "痞帅",
            "知性",
            "治癒",
            "治愈",
            "療癒",
            "疗愈",
            "綜藝擔",
            "综艺担",
            "性感",
            "憂鬱",
            "忧郁",
            "陽光",
            "阳光",
            "王子",
            "野性",
        )
        has_persona_term = any(term in compact for term in persona_terms)
        if has_persona_term:
            return True
        return (has_action and (has_preference_term or artist_mentioned)) or (
            has_member_target and (has_preference_term or artist_mentioned)
        )

    def ai_curator_preference_reply(self, context: MessageContext) -> Reply:
        # Stay in preference mode so the user can refine without the keyword gate.
        self._set_awaiting_preference(context.user_id)
        response = self._ai_curator_response(context.text, user_id=context.user_id)
        return Reply(
            report=response["report"],
            flex=response["flex"],
            alt_text="AI 入坑",
            text_first=True,
        )

    def ai_curator_reason_reply(self, context: MessageContext) -> Reply:
        response = self._ai_curator_reason_followup_response(context.text, user_id=context.user_id)
        return Reply(report=response["report"])

    def _ai_curator_response(self, message: str, user_id: str | None = None) -> dict:
        query = _clean_ai_curator_query(message)
        context = self._build_ai_curator_context(query)
        self._store_ai_curator_reason_context(user_id, context.get("recommended_members", []))
        fallback = _fallback_ai_curator_answer(query, context)
        report = self._generate_ai_curator_answer(query, context, fallback)
        return {
            "report": report,
            "flex": _build_ai_curator_followup_flex_contents(
                context.get("primary_artist"),
                context.get("recommended_members", []),
            ),
        }

    def _store_ai_curator_reason_context(
        self,
        user_id: str | None,
        recommended_members: list[dict[str, str]],
    ) -> None:
        if not user_id:
            return
        compact_members = [
            {
                "artist": recommendation.get("artist", "").strip(),
                "member": recommendation.get("member", "").strip(),
            }
            for recommendation in recommended_members[:3]
            if recommendation.get("artist", "").strip() and recommendation.get("member", "").strip()
        ]
        if compact_members:
            self.sessions.set(
                AI_CURATOR_REASON_CONTEXT_NAMESPACE,
                user_id,
                {"members": compact_members},
                AI_CURATOR_REASON_CONTEXT_TTL_SECONDS,
            )
        else:
            self.sessions.delete(AI_CURATOR_REASON_CONTEXT_NAMESPACE, user_id)

    def _ai_curator_reason_context_members(self, user_id: str) -> list[dict[str, str]]:
        entry = self.sessions.get(AI_CURATOR_REASON_CONTEXT_NAMESPACE, user_id)
        members = entry.get("members") if entry else None
        if not isinstance(members, list):
            return []
        return [member for member in members if isinstance(member, dict)]

    def _semantic_member_ranker(self) -> SemanticMemberRanker | None:
        # Loaded on first use: the encoder costs ~600MB and a second to open.
        if not self._semantic_ranker_loaded:
            self._semantic_ranker_loaded = True
            if self.semantic_ranker_loader is not None:
                self._semantic_ranker = self.semantic_ranker_loader()
        return self._semantic_ranker

    def _build_ai_curator_context(self, query: str) -> dict:
        ranker = self._semantic_member_ranker()
        if ranker is not None:
            # v2 understands the query through embeddings, so the tag profile only
            # steers the MV fallback; keywords suffice and save a Gemini call.
            profile = self._extract_ai_curator_preferences(query)
            profile["gender"] = profile["gender"] or query_gender(_compact_ai_curator_text(query))
            member_candidates = ranker.rank(query)[:5]
            member_notes = ranker.notes
            member_evidence = {
                member["id"]: picked
                for member in member_candidates
                if (picked := pick_member_evidence(ranker.evidence.get(member["id"], []), query))
            }
            low_confidence = False
        else:
            profile = self._resolve_ai_curator_profile(query)
            mv_artists = {
                row.get("artist", "").strip()
                for row in self.catalog.load_daily_kpop_rows("MV")
                if row.get("artist", "").strip()
            }
            member_candidates = _prioritize_members_with_mv(
                self._rank_bias_radar_members_for_curator(profile),
                mv_artists,
            )[:5]
            member_notes = {}
            member_evidence = {}
            low_confidence = not _ai_curator_profile_has_signal(profile)
        recommended_members = _ai_curator_recommended_members(member_candidates)
        recommended_artists = _ai_curator_recommended_artists(recommended_members)
        daily_items = self._rank_daily_mv_rows_for_artists(recommended_artists, profile)[:5]
        artist_candidates = _ai_curator_artist_candidates(member_candidates, daily_items)[:5]
        return {
            "query": query,
            "profile": profile,
            "member_candidates": member_candidates,
            "recommended_members": recommended_members,
            "daily_items": daily_items,
            "artist_summaries": self._load_ai_curator_artist_summaries(artist_candidates[:3]),
            "primary_artist": artist_candidates[0] if artist_candidates else None,
            "recommended_artists": recommended_artists,
            "member_notes": member_notes,
            "member_evidence": member_evidence,
            "low_confidence": low_confidence,
        }

    def _extract_ai_curator_preferences(self, query: str) -> dict[str, set[str] | str | None]:
        compact = unicodedata.normalize("NFKC", query).casefold().replace(" ", "")
        gender: str | None = None
        if "男團" in compact or "男偶像" in compact or "男idol" in compact:
            gender = "male"
        elif "女團" in compact or "女偶像" in compact or "女idol" in compact:
            gender = "female"

        tags = {
            "artists": self._extract_ai_curator_artist_preferences(compact),
            "appearance": _keyword_matches(
                compact,
                {
                    "貓咪": ("貓", "貓咪", "cat"),
                    "狗狗": ("狗狗", "狗系", "狗狗相", "dog"),
                    "小兔": ("兔", "兔子", "小兔", "rabbit"),
                    "狐狸": ("狐", "狐狸", "fox"),
                    "小鹿": ("鹿", "小鹿", "deer"),
                },
            ),
            "position": _keyword_matches(
                compact,
                {
                    "Vocal": ("vocal", "唱功", "主唱", "高音", "現場"),
                    "Dance": ("dance", "舞蹈", "跳舞", "舞台", "直拍"),
                    "Rap": ("rap", "rapper", "饒舌"),
                    "Visual": ("visual", "門面", "顏值", "外貌", "神顏"),
                    "All-rounder": ("all-rounder", "allrounder", "全能", "全方位"),
                },
            ),
            "vibe": _keyword_matches(
                compact,
                {
                    "冷感": ("冷感", "高冷"),
                    "甜系": ("甜", "甜系", "可愛"),
                    "霸氣": ("霸氣", "強勢", "帥"),
                    "反差": ("反差",),
                    "清冷": ("清冷", "仙", "乾淨"),
                },
            ),
            "relationship": _keyword_matches(
                compact,
                {
                    "戀愛感": ("戀愛感", "女友", "男友"),
                    "神性": ("神性", "神", "仙"),
                    "朋友感": ("朋友感", "親切"),
                    "白月光感": (
                        "白月光",
                        "白月光感",
                        "初戀",
                        "初戀感",
                        "守護",
                        "守護感",
                        "想保護",
                    ),
                    "舞台支配感": ("舞台支配", "舞台支配感", "壓場", "舞台強"),
                },
            ),
            "persona": _keyword_matches(
                compact,
                {
                    "姐系": ("姐系", "御姐", "姐姐", "大人感", "成熟", "氣場姐", "姐感"),
                    "忙內": ("忙內", "弟系", "maknae", "奶狗", "弟弟", "弟感"),
                    "鄰家": ("鄰家", "清純", "親和", "鄰家感", "好親近"),
                    "氛圍": ("氛圍", "氛圍感", "高級感", "神秘", "距離感"),
                    "元氣": ("元氣", "活潑", "開朗", "活力", "能量"),
                    "痞帥": ("痞帥", "痞痞", "壞壞", "壞男孩", "玩世不恭"),
                    "知性": ("知性", "才氣", "文藝", "書卷", "才華"),
                    "治癒": ("治癒", "療癒", "溫柔", "暖男", "暖系"),
                    "綜藝擔": ("綜藝", "綜藝擔", "搞笑", "諧星", "梗王"),
                    "性感": ("性感", "魅惑", "火辣", "sexy"),
                    "憂鬱感": ("憂鬱", "憂鬱感", "厭世", "陰鬱", "喪"),
                    "陽光": ("陽光", "大男孩", "陽光男孩", "活力外放"),
                    "王子": ("王子", "貴公子", "王子系", "紳士", "優雅"),
                    "野性": ("野性", "猛男", "狼系", "man味", "性張力"),
                },
            ),
        }
        return {"gender": gender, **tags}

    def _resolve_ai_curator_profile(self, query: str) -> dict[str, set[str] | str | None]:
        """Resolve a query into a preference profile.

        Gemini does the semantic understanding (so free-text like "姐系" maps onto the
        controlled vocabulary); the keyword matcher is a deterministic fallback that also
        contributes whatever it can match. The two results are merged so we never do worse
        than the old keyword-only behaviour.
        """

        base = self._extract_ai_curator_preferences(query)
        parsed = self._extract_ai_curator_preferences_via_gemini(query)
        if not parsed:
            return base

        merged: dict[str, set[str] | str | None] = dict(base)
        if not merged.get("gender") and parsed.get("gender"):
            merged["gender"] = parsed["gender"]
        for field in AI_CURATOR_PROFILE_FIELDS:
            base_tags = base.get(field) or set()
            parsed_tags = parsed.get(field) or set()
            merged[field] = set(base_tags) | set(parsed_tags)
        return merged

    def _extract_ai_curator_preferences_via_gemini(self, query: str) -> dict | None:
        if not self.llm.enabled:
            return None
        try:
            prompt = _build_ai_curator_profile_prompt(query)
            text = self.llm.generate(
                prompt,
                temperature=0.0,
                max_output_tokens=220,
                response_mime_type="application/json",
            )
            return _parse_ai_curator_profile_json(text)
        except Exception as error:
            logger.warning(
                "AI curator profile parse via Gemini failed (%s); using keyword fallback.",
                _llm_error(error),
            )
            return None

    def _extract_ai_curator_artist_preferences(self, compact_query: str) -> set[str]:
        return {
            artist
            for artist in self._ai_curator_known_artists()
            if _compact_ai_curator_text(artist) in compact_query
        }

    def _ai_curator_query_mentions_known_artist(self, compact_query: str) -> bool:
        return any(
            _compact_ai_curator_text(artist) in compact_query
            for artist in self._ai_curator_known_artists()
        )

    def _ai_curator_known_artists(self) -> list[str]:
        artists = []
        for member in self.catalog.load_bias_radar_members():
            artists.append(member.get("artist", "").strip())
        for category in ("MV", "直拍", "經典舞台"):
            for row in self.catalog.load_daily_kpop_rows(category):
                artists.append(row.get("artist", "").strip())
        return list(dict.fromkeys(artist for artist in artists if artist))

    def _rank_bias_radar_members_for_curator(self, profile: dict) -> list[dict[str, str]]:
        scored: list[tuple[int, dict[str, str]]] = []
        preferred_artists = {
            artist.casefold()
            for artist in (profile.get("artists") or set())
            if isinstance(artist, str)
        }
        for member in self.catalog.load_bias_radar_members():
            score = 0
            artist = member.get("artist", "").strip()
            if preferred_artists and artist.casefold() in preferred_artists:
                score += 8
            gender = profile.get("gender")
            if gender and member.get("gender_group") == gender:
                score += 3
            elif not gender:
                score += 1
            for field in AI_CURATOR_PROFILE_FIELDS:
                wanted = profile.get(field) or set()
                matched = wanted & split_bias_radar_tags(member.get(field, ""))
                score += len(matched) * 2
            if score > 0:
                scored.append((score, member))
        self.rng.shuffle(scored)
        scored.sort(key=lambda item: item[0], reverse=True)
        return [member for _, member in scored]

    def _rank_daily_mv_rows_for_artists(
        self,
        artists: list[str],
        profile: dict,
    ) -> list[dict[str, str]]:
        rows = self.catalog.load_daily_kpop_rows("MV")
        if not rows:
            return []

        if not artists:
            return self._rank_daily_kpop_rows_for_curator("MV", profile)

        matched_rows = [
            row
            for row in rows
            if any(same_lookup_name(row.get("artist", ""), artist) for artist in artists)
        ]
        # 沒有已顯示推薦團體的 MV 時，省略入口，避免帶使用者去無關團體。

        self.rng.shuffle(matched_rows)
        return matched_rows

    def _rank_daily_kpop_rows_for_curator(
        self, category: str, profile: dict
    ) -> list[dict[str, str]]:
        rows = self.catalog.load_daily_kpop_rows(category)
        if not rows and category != "MV":
            rows = self.catalog.load_daily_kpop_rows("MV")
        self.rng.shuffle(rows)
        gender = profile.get("gender")
        if gender == "female":
            rows.sort(key=lambda row: 0 if _daily_artist_looks_female(row.get("artist", "")) else 1)
        elif gender == "male":
            rows.sort(
                key=lambda row: 0 if not _daily_artist_looks_female(row.get("artist", "")) else 1
            )
        return rows

    def _load_ai_curator_artist_summaries(self, artists: list[str]) -> list[dict[str, str]]:
        summaries = []
        for artist in artists:
            cache_path = (
                self.catalog.base_dir / "data" / "cache" / "artists" / f"{artist.lower()}.json"
            )
            if not cache_path.exists():
                continue
            try:
                payload = json.loads(cache_path.read_text(encoding="utf-8"))
            except Exception:
                continue
            sentiment = payload.get("sources", {}).get("sentiment", {}).get("sentiment", {})
            chart = payload.get("sources", {}).get("chart", {})
            insight = payload.get("insight", {})
            summaries.append(
                {
                    "artist": artist,
                    "chart": (
                        f"best_rank={chart.get('best_rank', 'NA')}, "
                        f"trend={chart.get('trend', 'NA')}"
                    ),
                    "sentiment": (
                        f"positive={sentiment.get('positive', 0)}, "
                        f"neutral={sentiment.get('neutral', 0)}, "
                        f"negative={sentiment.get('negative', 0)}"
                    ),
                    "insight": insight.get("headline", ""),
                }
            )
        return summaries

    def _generate_ai_curator_answer(self, query: str, context: dict, fallback: str) -> str:
        members = context.get("member_candidates", [])[:AI_CURATOR_ANSWER_MEMBERS]
        if not self.llm.enabled or not members:
            return fallback
        try:
            text = self.llm.generate(
                _build_ai_curator_prompt(query, context),
                temperature=0.45,
                max_output_tokens=360,
                response_mime_type="application/json",
            )
        except Exception as error:
            logger.warning(
                "AI curator Gemini response failed (%s); using fallback.", _llm_error(error)
            )
            return fallback
        reasons = _parse_ai_curator_reasons(text, len(members))
        if not any(reasons):
            logger.warning(
                "AI curator Gemini reasons rejected (%d chars); using fallback.", len(text)
            )
            return fallback
        return _render_ai_curator_answer(query, context, reasons)

    def _ai_curator_reason_followup_response(
        self,
        message: str,
        user_id: str | None = None,
    ) -> dict:
        explicit_member_row = self._find_ai_curator_reason_member(message)
        if explicit_member_row and contains_lookup_name(
            message,
            explicit_member_row.get("artist", ""),
        ):
            member_row = explicit_member_row
        else:
            member_row = self._find_ai_curator_reason_member_from_context(message, user_id)
        if member_row is None:
            member_row = explicit_member_row
        if member_row:
            fallback = self._fallback_ai_curator_reason_answer(member_row)
            reason = self._generate_ai_curator_reason_answer(message, member_row, fallback)
            link_text = self._find_recommendation_link_for_member(member_row)
            return {"report": fit_line_text(join_nonempty_blocks(reason, link_text))}

        artist = self._find_ai_curator_reason_artist(message)
        if artist:
            summary_text = _ai_curator_artist_summary_text(
                self._load_ai_curator_artist_summary(artist)
            )
            link_text = self._find_recommendation_link_for_artist(artist)
            lines = [
                f"目前追問主要支援成員；你問到的是 {artist}，我先用本地資料補一個團體入口。",
                summary_text,
                link_text,
            ]
            return {"report": fit_line_text(join_nonempty_blocks(*lines))}

        fallback_link = self._find_random_daily_mv_link_text()
        return {
            "report": fit_line_text(
                join_nonempty_blocks(
                    "目前本地資料還找不到這位成員，但可以先從本命雷達或每日一首繼續探索。",
                    fallback_link,
                )
            )
        }

    def _find_ai_curator_reason_member_from_context(
        self,
        message: str,
        user_id: str | None,
    ) -> dict[str, str] | None:
        if not user_id:
            return None
        recommendations = self._ai_curator_reason_context_members(user_id)
        if not recommendations:
            return None
        members = self._load_ai_curator_reason_members()
        for recommendation in recommendations:
            rec_member = recommendation.get("member", "")
            rec_artist = recommendation.get("artist", "")
            if not contains_lookup_name(message, rec_member):
                continue
            for member in members:
                if same_lookup_name(member.get("artist", ""), rec_artist) and same_lookup_name(
                    member.get("member", ""),
                    rec_member,
                ):
                    return member
        return None

    def _find_ai_curator_reason_member(self, message: str) -> dict[str, str] | None:
        for member in self._load_ai_curator_reason_members():
            if contains_lookup_name(message, member.get("artist", "")) and contains_lookup_name(
                message,
                member.get("member", ""),
            ):
                return member
        for member in self._load_ai_curator_reason_members():
            if contains_lookup_name(message, member.get("member", "")):
                return member
        return None

    def _find_ai_curator_reason_artist(self, message: str) -> str | None:
        artists = []
        for member in self._load_ai_curator_reason_members():
            artists.append(member.get("artist", "").strip())
        for mv_row in self.catalog.load_daily_kpop_rows("MV"):
            artists.append(mv_row.get("artist", "").strip())

        for artist in dict.fromkeys(artist for artist in artists if artist):
            if contains_lookup_name(message, artist):
                return artist
        return None

    def _load_ai_curator_reason_members(self) -> list[dict[str, str]]:
        csv_path = self.catalog.base_dir / "data" / "play_zone" / "bias_radar_members.csv"
        return self.catalog.load_cached_csv_rows(csv_path, _ai_curator_reason_member_is_usable)

    def _fallback_ai_curator_reason_answer(self, member_row: dict[str, str]) -> str:
        member = display_member_name(member_row.get("member", ""))
        return self._render_ai_curator_reason_answer(
            member_row, _ai_curator_reason_sentences(member_row, member)
        )

    def _render_ai_curator_reason_answer(
        self,
        member_row: dict[str, str],
        reason_sentences: list[str],
    ) -> str:
        """追問回覆的固定版面：✨ 推誰、🔎／💫 理由、📰 團體近況；🎬 直拍由呼叫端接在後面。"""

        artist = member_row.get("artist", "").strip()
        member = display_member_name(member_row.get("member", ""))
        lines = [f"✨ 我會先推 {artist} {member}。"]
        if reason_sentences:
            lines.extend(reason_sentences)
        else:
            lines.append("🔎 這位的線索比較少，我會先讓你從團體影片開始抓感覺。")

        summary_text = _ai_curator_artist_summary_text(self._load_ai_curator_artist_summary(artist))
        if summary_text:
            lines.append(summary_text)
        return "\n".join(lines)

    def _generate_ai_curator_reason_answer(
        self,
        message: str,
        member_row: dict[str, str],
        fallback: str,
    ) -> str:
        if not self.llm.enabled:
            return fallback
        try:
            prompt = self._build_ai_curator_reason_prompt(message, member_row)
            text = self.llm.generate(prompt, temperature=0.35, max_output_tokens=260)
        except Exception as error:
            logger.warning(
                "AI curator reason Gemini response failed (%s); using fallback.", _llm_error(error)
            )
            return fallback
        sentences = _parse_ai_curator_reason_sentences(text)
        if sentences is None:
            logger.warning("AI curator reason Gemini reply unusable; using fallback.")
            return fallback
        return self._render_ai_curator_reason_answer(member_row, sentences)

    def _build_ai_curator_reason_prompt(self, message: str, member_row: dict[str, str]) -> str:
        """Gemini 只寫 🔎、💫 兩句，開頭、團體近況和直拍由程式照固定版面補上。"""

        artist = member_row.get("artist", "").strip()
        member = display_member_name(member_row.get("member", ""))
        return f"""你是 K-pop AI 入坑推薦理由助理，請用繁體中文（台灣用語）回答使用者追問。
    只能根據下方本地成員資料寫，不要捏造沒有列出的特點。
    請寫兩句推坑理由，每句 25 到 60 字：
    - 第一句：第一眼會被什麼吸引（長相、氣質），可以用「如果你吃…」開頭，並帶出 {member}。
    - 第二句：為什麼會想慢慢陷進去（關係感、反差），最後說入門可以先看能感受到哪種魅力的直拍。
    語氣要像自然推坑，不要逐欄列出資料表。
    不要直接說「外貌、定位、氣質、關係感、資料、標籤、欄位」，要把線索揉進自然句子。
    不要加 emoji、網址或編號（版面和直拍連結由系統另外補上）。
    只輸出 JSON 字串陣列，例如 ["第一句", "第二句"]。

    使用者追問：
    {message}

    本地成員資料：
    - artist: {artist}
    - member: {member}
    - appearance: {bias_radar_tag_text(member_row.get("appearance", "")) or "無"}
    - position: {bias_radar_tag_text(member_row.get("position", "")) or "無"}
    - vibe: {bias_radar_tag_text(member_row.get("vibe", "")) or "無"}
    - relationship: {bias_radar_tag_text(member_row.get("relationship", "")) or "無"}
    """

    def _find_recommendation_link_for_member(self, member_row: dict[str, str]) -> str:
        member = member_row.get("member", "").strip()
        artist = member_row.get("artist", "").strip()
        fancams = self.catalog.load_daily_kpop_rows("直拍")

        member_fancams = [
            row
            for row in fancams
            if same_lookup_name(row.get("artist", ""), artist)
            and same_lookup_name(row.get("member", ""), member)
        ]
        if member_fancams:
            return _format_fancam_link(self.rng.choice(member_fancams), "🎬 先用這支直拍確認感覺：")

        member_fancams = [row for row in fancams if same_lookup_name(row.get("member", ""), member)]
        if member_fancams:
            return _format_fancam_link(
                self.rng.choice(member_fancams),
                f"🎬 目前沒有找到 {display_member_name(member)} 的同團直拍，先補一支同名成員直拍：",
            )

        artist_fancams = [row for row in fancams if same_lookup_name(row.get("artist", ""), artist)]
        if artist_fancams:
            return _format_fancam_link(
                self.rng.choice(artist_fancams),
                f"🎬 目前沒有找到 {display_member_name(member)} 的直拍，先補一支同團直拍：",
            )

        artist_mvs = [
            row
            for row in self.catalog.load_daily_kpop_rows("MV")
            if same_lookup_name(row.get("artist", ""), artist)
        ]
        if artist_mvs:
            return _format_mv_link(
                self.rng.choice(artist_mvs),
                f"🎬 目前沒有找到 {display_member_name(member)} 的直拍，先補一支所屬團體 MV：",
            )

        return self._find_random_daily_mv_link_text(
            f"🎬 目前沒有找到 {display_member_name(member)} 的直拍，先補一支每日 MV："
        )

    def _find_recommendation_link_for_artist(self, artist: str) -> str:
        artist_mvs = [
            row
            for row in self.catalog.load_daily_kpop_rows("MV")
            if same_lookup_name(row.get("artist", ""), artist)
        ]
        if artist_mvs:
            return _format_mv_link(self.rng.choice(artist_mvs), "先補一支團體 MV：")
        return self._find_random_daily_mv_link_text()

    def _find_random_daily_mv_link_text(self, prefix: str = "先補一支每日 MV：") -> str:
        mv_rows = self.catalog.load_daily_kpop_rows("MV")
        if not mv_rows:
            return ""
        return _format_mv_link(self.rng.choice(mv_rows), prefix)

    def _load_ai_curator_artist_summary(self, artist: str) -> dict[str, str] | None:
        summaries = self._load_ai_curator_artist_summaries([artist])
        return summaries[0] if summaries else None
