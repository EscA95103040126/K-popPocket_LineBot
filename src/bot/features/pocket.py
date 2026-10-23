from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from urllib.parse import parse_qsl

from src.bot.dispatcher import MessageContext
from src.bot.flex_common import (
    KPOP_RADAR_ACCENT_COLOR,
    build_daily_kpop_redraw_flex_contents,
    build_single_redraw_flex_contents,
    kpop_radar_save_button,
    single_redraw_button,
)
from src.bot.reply import QuickReplyAction, Reply

if TYPE_CHECKING:
    from src.tools.kpop_radar import KpopRadarRepository

logger = logging.getLogger(__name__)


KPOP_RADAR_TRIGGERS = {
    "我的口袋",
    "我的 K-pop 口袋",
    "我的K-pop口袋",
    "K-pop 口袋",
    "K-pop口袋",
    "KPOP口袋",
    "口袋",
    "我的 K-pop 雷達",
    "我的K-pop雷達",
    "K-pop 雷達",
    "K-pop雷達",
    "KPOP雷達",
    "我的收藏",
    "收藏庫",
}
KPOP_RADAR_ACTIONS = {
    "open_radar",
    "view_saved",
    "open_pref",
    "set_pref",
    "save_item",
}
KPOP_RADAR_BODY_COLOR = "#FFF6F0"
KPOP_RADAR_SUBTITLE_COLOR = "#FFE9DF"
KPOP_RADAR_TEXT_COLOR = "#5C3F37"
KPOP_RADAR_MUTED_TEXT_COLOR = "#7A6258"
KPOP_RADAR_ITEM_LABELS = {
    "mv": ("🎬", "MV", "個"),
    "fancam": ("🎥", "直拍", "個"),
    "photo": ("🖼️", "照片", "張"),
}
KPOP_RADAR_GENDER_LABELS = {
    "girl_group": "女團",
    "boy_group": "男團",
    "all": "都可以",
}


def _build_kpop_radar_flex_contents(
    preferred_gender: str,
    counts: dict[str, int],
) -> dict:
    preference_label = KPOP_RADAR_GENDER_LABELS.get(preferred_gender, "都可以")
    return {
        "type": "bubble",
        "size": "mega",
        "header": {
            "type": "box",
            "layout": "vertical",
            "backgroundColor": KPOP_RADAR_ACCENT_COLOR,
            "paddingAll": "18px",
            "contents": [
                {
                    "type": "text",
                    "text": "收藏庫",
                    "size": "xs",
                    "color": KPOP_RADAR_SUBTITLE_COLOR,
                },
                {
                    "type": "text",
                    "text": "我的K-pop 口袋",
                    "size": "xl",
                    "weight": "bold",
                    "color": "#FFFFFF",
                    "margin": "sm",
                },
            ],
        },
        "body": {
            "type": "box",
            "layout": "vertical",
            "backgroundColor": KPOP_RADAR_BODY_COLOR,
            "paddingAll": "18px",
            "spacing": "md",
            "contents": [
                {
                    "type": "text",
                    "text": "收藏 MV、直拍與照片，建立你的專屬 K-pop 收藏庫。",
                    "size": "sm",
                    "color": KPOP_RADAR_TEXT_COLOR,
                    "wrap": True,
                },
                {
                    "type": "box",
                    "layout": "vertical",
                    "spacing": "xs",
                    "paddingAll": "12px",
                    "backgroundColor": "#FFFFFF",
                    "cornerRadius": "8px",
                    "contents": [
                        _kpop_radar_info_text(f"目前推薦偏好：{preference_label}"),
                        _kpop_radar_info_text(
                            f"🎬 收藏過的 MV：{counts.get('mv', 0)} 個"
                        ),
                        _kpop_radar_info_text(
                            f"🎥 收藏過的直拍：{counts.get('fancam', 0)} 個"
                        ),
                        _kpop_radar_info_text(
                            f"🖼️ 收藏過的照片：{counts.get('photo', 0)} 張"
                        ),
                    ],
                },
                {
                    "type": "text",
                    "text": "收藏越多，每日推薦會越貼近你的喜好。",
                    "size": "xs",
                    "color": KPOP_RADAR_MUTED_TEXT_COLOR,
                    "wrap": True,
                },
                _kpop_radar_button("查看 MV 收藏", "action=view_saved&type=mv"),
                _kpop_radar_button("查看直拍收藏", "action=view_saved&type=fancam"),
                _kpop_radar_button("查看照片收藏", "action=view_saved&type=photo"),
                _kpop_radar_button("修改推薦偏好", "action=open_pref", primary=True),
            ],
        },
    }


def _kpop_radar_info_text(text: str) -> dict:
    return {
        "type": "text",
        "text": text,
        "size": "sm",
        "color": KPOP_RADAR_TEXT_COLOR,
        "wrap": True,
    }


def _kpop_radar_button(label: str, data: str, primary: bool = False) -> dict:
    button = {
        "type": "button",
        "style": "primary" if primary else "secondary",
        "height": "sm",
        "action": {
            "type": "postback",
            "label": label,
            "data": data,
        },
    }
    if primary:
        button["color"] = KPOP_RADAR_ACCENT_COLOR
    return button


def _build_kpop_radar_preference_flex_contents() -> dict:
    return {
        "type": "bubble",
        "size": "kilo",
        "header": {
            "type": "box",
            "layout": "vertical",
            "backgroundColor": KPOP_RADAR_ACCENT_COLOR,
            "paddingAll": "14px",
            "contents": [
                {
                    "type": "text",
                    "text": "修改推薦偏好",
                    "size": "md",
                    "weight": "bold",
                    "color": "#FFFFFF",
                },
            ],
        },
        "body": {
            "type": "box",
            "layout": "vertical",
            "backgroundColor": KPOP_RADAR_BODY_COLOR,
            "paddingAll": "14px",
            "spacing": "sm",
            "contents": [
                _kpop_radar_preference_button("女團", "girl_group"),
                _kpop_radar_preference_button("男團", "boy_group"),
                _kpop_radar_preference_button("都可以", "all"),
            ],
        },
    }


def _kpop_radar_preference_button(label: str, preferred_gender: str) -> dict:
    return {
        "type": "button",
        "style": "primary",
        "height": "sm",
        "color": KPOP_RADAR_ACCENT_COLOR,
        "action": {
            "type": "postback",
            "label": label,
            "data": f"action=set_pref&gender={preferred_gender}",
        },
    }


def build_kpop_radar_preference_quick_reply() -> tuple[QuickReplyAction, ...]:
    return tuple(
        QuickReplyAction(label=label, text=f"action=set_pref&gender={gender}", postback=True)
        for label, gender in (
            ("女團", "girl_group"),
            ("男團", "boy_group"),
            ("都可以", "all"),
        )
    )


def _format_kpop_radar_saved_items(
    item_type: str,
    items: list[dict[str, object]],
) -> str:
    icon, label, _unit = KPOP_RADAR_ITEM_LABELS.get(
        item_type,
        KPOP_RADAR_ITEM_LABELS["mv"],
    )
    if not items:
        return f"{icon} 你的 {label} 收藏\n\n目前還沒有收藏。"
    lines = [f"{icon} 你的 {label} 收藏", ""]
    for index, item in enumerate(items[:20], start=1):
        artist = str(item.get("artist") or "").strip()
        title = str(item.get("title") or "").strip()
        member = str(item.get("member") or "").strip()
        url = str(item.get("url") or "").strip()
        name = f"{artist} - {title}" if artist else title
        if member:
            name = f"{name} ({member})"
        lines.append(f"{index}. {name}")
        if url:
            lines.append(f"   🔗 {url}")
    return "\n".join(lines)


def is_kpop_radar_request(message: str) -> bool:
    normalized = message.strip()
    compact = normalized.casefold().replace(" ", "")
    if normalized in KPOP_RADAR_TRIGGERS:
        return True
    if compact in {trigger.casefold().replace(" ", "") for trigger in KPOP_RADAR_TRIGGERS}:
        return True
    return _kpop_radar_action(message) in KPOP_RADAR_ACTIONS


def _kpop_radar_action(message: str) -> str:
    return _kpop_radar_params(message).get("action", "")


def _kpop_radar_param(message: str, key: str, default: str = "") -> str:
    return _kpop_radar_params(message).get(key, default)


def _kpop_radar_params(message: str) -> dict[str, str]:
    data = message.strip()
    if "=" not in data:
        return {}
    return {
        str(key): str(value)
        for key, value in parse_qsl(data, keep_blank_values=True)
    }


def _build_kpop_radar_save_prompt_flex_contents(
    recommendation: dict[str, object],
    category: str,
    *,
    redraw_label: str,
    redraw_text: str,
) -> dict:
    item_id = str(recommendation.get("id") or "")
    item_type = str(recommendation.get("item_type") or "mv")
    label = "收藏至口袋"
    contents = [
        {
            "type": "text",
            "text": "喜歡這個推薦嗎？",
            "size": "xs",
            "color": KPOP_RADAR_TEXT_COLOR,
            "wrap": True,
        },
    ]
    if item_id:
        contents.append(kpop_radar_save_button(item_id, label=label))
    contents.append(single_redraw_button(redraw_label, redraw_text))
    return {
        "type": "bubble",
        "size": "kilo",
        "body": {
            "type": "box",
            "layout": "vertical",
            "backgroundColor": KPOP_RADAR_BODY_COLOR,
            "paddingAll": "14px",
            "spacing": "sm",
            "contents": contents,
        },
    }


def _kpop_radar_item_type_label(item_type: str) -> str:
    return {
        "mv": "MV",
        "fancam": "直拍",
        "photo": "照片",
    }.get(item_type, "內容")


class PocketFeature:
    """My K-pop Pocket: saved items and daily MV preferences stored in Supabase."""

    def __init__(self, radar_repo: KpopRadarRepository) -> None:
        self.radar_repo = radar_repo

    def _kpop_radar_response(self, message: str, user_id: str = "analyze-user") -> dict:
        action = _kpop_radar_action(message)
        try:
            self.ensure_kpop_radar_user(user_id)
            if action == "view_saved":
                item_type = _kpop_radar_param(message, "type", "mv")
                return self._kpop_radar_saved_response(user_id, item_type)
            if action == "open_pref":
                return {
                    "report": "請選擇你的每日 MV 推薦偏好。",
                    "flex": _build_kpop_radar_preference_flex_contents(),
                }
            if action == "set_pref":
                preferred_gender = _kpop_radar_param(message, "gender", "all")
                return self._kpop_radar_set_preference_response(user_id, preferred_gender)
            if action == "save_item":
                item_id = _kpop_radar_param(message, "item_id", "")
                return self._kpop_radar_save_item_response(user_id, item_id)
            return self._kpop_radar_home_response(user_id)
        except Exception:
            logger.exception("K-pop Radar response failed.")
            return {
                "report": "我的K-pop 口袋暫時連不上資料庫，晚點再試一次。",
                "flex": None,
            }

    def ensure_kpop_radar_user(self, user_id: str) -> None:
        if user_id:
            self.radar_repo.ensure_user(user_id)

    def _kpop_radar_home_response(self, user_id: str) -> dict:
        preferred_gender = self.radar_repo.get_preference(user_id)
        counts = self.radar_repo.saved_counts(user_id)
        return {
            "report": "我的K-pop 口袋",
            "flex": _build_kpop_radar_flex_contents(preferred_gender, counts),
        }

    def _kpop_radar_saved_response(self, user_id: str, item_type: str) -> dict:
        if item_type not in KPOP_RADAR_ITEM_LABELS:
            item_type = "mv"
        items = self.radar_repo.list_saved_items(user_id, item_type)
        return {
            "report": _format_kpop_radar_saved_items(item_type, items),
            "flex": None,
        }

    def _kpop_radar_set_preference_response(self, user_id: str, preferred_gender: str) -> dict:
        if preferred_gender not in KPOP_RADAR_GENDER_LABELS:
            preferred_gender = "all"
        updated = self.radar_repo.upsert_preference(user_id, preferred_gender)
        counts = self.radar_repo.saved_counts(user_id)
        label = KPOP_RADAR_GENDER_LABELS.get(updated, "都可以")
        return {
            "report": f"已更新每日 MV 推薦偏好：{label}",
            "flex": _build_kpop_radar_flex_contents(updated, counts),
        }

    def _kpop_radar_save_item_response(self, user_id: str, item_id: str) -> dict:
        if not item_id:
            return {"report": "找不到要收藏的內容。", "flex": None}
        result = self.radar_repo.save_item(user_id, item_id)
        if result.saved:
            preferred_gender = self.radar_repo.get_preference(user_id)
            counts = self.radar_repo.saved_counts(user_id)
            return {
                "report": "已加入你的 K-pop 口袋 ⭐",
                "flex": _build_kpop_radar_flex_contents(preferred_gender, counts),
            }
        if result.duplicate:
            preferred_gender = self.radar_repo.get_preference(user_id)
            counts = self.radar_repo.saved_counts(user_id)
            return {
                "report": "這個內容已經在你的口袋裡了 ⭐",
                "flex": _build_kpop_radar_flex_contents(preferred_gender, counts),
            }
        if result.status == "missing":
            return {"report": "找不到這個 K-pop 內容，可能已被移除。", "flex": None}
        return {"report": "K-pop 口袋尚未設定 Supabase，暫時無法收藏。", "flex": None}

    def kpop_radar_reply(self, context: MessageContext) -> Reply:
        response = self._kpop_radar_response(context.text, user_id=context.user_id)
        if _kpop_radar_action(context.text) == "open_pref":
            return Reply(
                report=response["report"],
                flex=response["flex"],
                alt_text="修改推薦偏好",
                text_first=True,
                quick_replies=build_kpop_radar_preference_quick_reply(),
            )
        return Reply(report=response["report"], flex=response["flex"], alt_text="我的K-pop 口袋")

    def build_recommendation_action_flex_contents(
        self,
        *,
        item_type: str,
        url: str,
        redraw_label: str,
        redraw_text: str,
        daily_redraw: bool = False,
        fallback_flex: dict | None = None,
    ) -> dict:
        item = None
        if item_type and self.radar_repo.enabled:
            try:
                item = self.radar_repo.find_item_by_url(item_type, url)
            except Exception:
                logger.exception("Could not look up K-pop Radar item for save button.")
        if item:
            if daily_redraw:
                return build_daily_kpop_redraw_flex_contents(
                    save_item_id=str(item.get("id") or "")
                )
            return _build_kpop_radar_save_prompt_flex_contents(
                item,
                _kpop_radar_item_type_label(item_type),
                redraw_label=redraw_label,
                redraw_text=redraw_text,
            )
        return fallback_flex or build_single_redraw_flex_contents(redraw_label, redraw_text)
