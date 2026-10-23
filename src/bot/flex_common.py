from __future__ import annotations

PLAY_ZONE_ACCENT_COLOR = "#5D6F66"
PLAY_ZONE_BODY_COLOR = "#F7FAF8"
PLAY_ZONE_SUBTITLE_COLOR = "#EAF4EE"
PLAY_ZONE_TEXT_COLOR = "#3F554A"
PLAY_ZONE_MUTED_TEXT_COLOR = "#4F665B"
KPOP_RADAR_ACCENT_COLOR = "#B76E61"


def daily_redraw_button(label: str, text: str) -> dict:
    return {
        "type": "button",
        "style": "primary",
        "height": "sm",
        "color": "#4E779A",
        "action": {
            "type": "message",
            "label": label,
            "text": text,
        },
    }


def selection_page_flex_contents(
    *,
    title: str,
    subtitle: str,
    description: str,
    accent_color: str,
    body_background: str = "#FAF7F4",
    subtitle_color: str = "#FDEBD8",
    description_color: str = "#5C4033",
    item_description_color: str = "#6B4A3E",
    items: list[dict[str, str]],
) -> dict:
    return {
        "type": "bubble",
        "size": "mega",
        "header": {
            "type": "box",
            "layout": "vertical",
            "backgroundColor": accent_color,
            "paddingAll": "18px",
            "contents": [
                {
                    "type": "text",
                    "text": subtitle,
                    "size": "xs",
                    "color": subtitle_color,
                },
                {
                    "type": "text",
                    "text": title,
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
            "backgroundColor": body_background,
            "paddingAll": "18px",
            "spacing": "md",
            "contents": [
                {
                    "type": "text",
                    "text": description,
                    "size": "sm",
                    "color": description_color,
                    "wrap": True,
                },
                *[
                    _selection_page_button(
                        item,
                        accent_color,
                        item_description_color,
                    )
                    for item in items
                ],
            ],
        },
    }


def _selection_page_button(
    item: dict[str, str],
    accent_color: str,
    description_color: str,
) -> dict:
    return {
        "type": "box",
        "layout": "horizontal",
        "spacing": "md",
        "paddingAll": "12px",
        "backgroundColor": "#FFFFFF",
        "cornerRadius": "8px",
        "action": {"type": "message", "text": item["text"]},
        "contents": [
            {
                "type": "text",
                "text": item["icon"],
                "size": "xl",
                "flex": 0,
                "gravity": "center",
            },
            {
                "type": "box",
                "layout": "vertical",
                "spacing": "xs",
                "contents": [
                    {
                        "type": "text",
                        "text": item["title"],
                        "size": "md",
                        "weight": "bold",
                        "color": accent_color,
                    },
                    {
                        "type": "text",
                        "text": item["description"],
                        "size": "xs",
                        "color": description_color,
                        "wrap": True,
                    },
                ],
            },
        ],
    }


def build_single_redraw_flex_contents(label: str, text: str) -> dict:
    return {
        "type": "bubble",
        "size": "kilo",
        "body": {
            "type": "box",
            "layout": "vertical",
            "backgroundColor": "#F4F8FC",
            "paddingAll": "14px",
            "spacing": "sm",
            "contents": [
                {
                    "type": "text",
                    "text": "想再抽一次嗎？",
                    "size": "xs",
                    "color": "#314B60",
                    "wrap": True,
                },
                single_redraw_button(label, text),
            ],
        },
    }


def single_redraw_button(label: str, text: str) -> dict:
    if text == "神圖抽卡":
        return {
            "type": "button",
            "style": "primary",
            "height": "sm",
            "color": PLAY_ZONE_ACCENT_COLOR,
            "action": {
                "type": "message",
                "label": label,
                "text": text,
            },
        }
    return daily_redraw_button(label, text)


def build_daily_kpop_redraw_flex_contents(save_item_id: str = "") -> dict:
    body_contents = [
        {
            "type": "text",
            "text": "想再抽哪一種 K-pop 推薦？",
            "size": "xs",
            "color": "#314B60",
            "wrap": True,
        },
        {
            "type": "box",
            "layout": "horizontal",
            "spacing": "sm",
            "contents": [
                daily_redraw_button("MV", "每日 MV"),
                daily_redraw_button("直拍", "每日直拍"),
                daily_redraw_button("舞台", "每日經典舞台"),
            ],
        },
    ]
    if save_item_id:
        body_contents.append(kpop_radar_save_button(save_item_id))

    return {
        "type": "bubble",
        "size": "kilo",
        "header": {
            "type": "box",
            "layout": "vertical",
            "backgroundColor": "#4E779A",
            "paddingAll": "14px",
            "contents": [
                {
                    "type": "text",
                    "text": "再抽一首",
                    "size": "md",
                    "weight": "bold",
                    "color": "#FFFFFF",
                },
            ],
        },
        "body": {
            "type": "box",
            "layout": "vertical",
            "backgroundColor": "#F4F8FC",
            "paddingAll": "14px",
            "spacing": "sm",
            "contents": body_contents,
        },
    }


def kpop_radar_save_button(item_id: str, label: str = "收藏至口袋") -> dict:
    return {
        "type": "button",
        "style": "primary",
        "height": "sm",
        "color": KPOP_RADAR_ACCENT_COLOR,
        "action": {
            "type": "postback",
            "label": label,
            "data": f"action=save_item&item_id={item_id}",
        },
    }
