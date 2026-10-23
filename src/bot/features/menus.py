from __future__ import annotations

from src.agent import SUPPORTED_ARTISTS
from src.bot.dispatcher import MessageContext
from src.bot.flex_common import (
    PLAY_ZONE_ACCENT_COLOR,
    PLAY_ZONE_BODY_COLOR,
    PLAY_ZONE_MUTED_TEXT_COLOR,
    PLAY_ZONE_SUBTITLE_COLOR,
    PLAY_ZONE_TEXT_COLOR,
)
from src.bot.flex_common import selection_page_flex_contents
from src.bot.reply import Reply


def _artist_picker_flex_contents() -> dict:
    return {
        "type": "bubble",
        "size": "mega",
        "header": {
            "type": "box",
            "layout": "vertical",
            "backgroundColor": "#C4956A",
            "paddingAll": "18px",
            "contents": [
                {
                    "type": "text",
                    "text": "K-pop Agent",
                    "size": "xs",
                    "color": "#FDEBD8",
                },
                {
                    "type": "text",
                    "text": "選擇藝人",
                    "size": "xxl",
                    "weight": "bold",
                    "color": "#FFFFFF",
                    "margin": "sm",
                },
            ],
        },
        "body": {
            "type": "box",
            "layout": "vertical",
            "backgroundColor": "#FAF7F4",
            "paddingAll": "18px",
            "spacing": "md",
            "contents": [
                {
                    "type": "text",
                    "text": "請選擇要產生分析報告的藝人，或直接輸入「分析 藝人名」。",
                    "size": "sm",
                    "color": "#5C4033",
                    "wrap": True,
                },
                *[
                    _artist_picker_button(artist, f"分析 {artist}")
                    for artist in SUPPORTED_ARTISTS
                ],
            ],
        },
    }


def _artist_picker_button(label: str, text: str) -> dict:
    return {
        "type": "button",
        "style": "primary",
        "height": "sm",
        "color": "#8B5E52",
        "action": {
            "type": "message",
            "label": label,
            "text": text,
        },
    }


def _build_play_zone_flex_contents() -> dict:
    return selection_page_flex_contents(
        title="K-pop Play Zone",
        subtitle="選一個互動玩法",
        description="把既有資料包成 LINE 互動體驗：測驗、雷達、認人與抽卡。",
        accent_color=PLAY_ZONE_ACCENT_COLOR,
        body_background=PLAY_ZONE_BODY_COLOR,
        subtitle_color=PLAY_ZONE_SUBTITLE_COLOR,
        description_color=PLAY_ZONE_TEXT_COLOR,
        item_description_color=PLAY_ZONE_MUTED_TEXT_COLOR,
        items=[
            {
                "icon": "🧭",
                "title": "本命雷達測驗",
                "description": "用幾題選擇題推測最適合你的團體與本命。",
                "text": "本命雷達測驗",
            },
            {
                "icon": "💬",
                "title": "粉絲屬性測驗",
                "description": "5 題判斷你是團飯、唯飯還是跟風粉。",
                "text": "粉絲屬性測驗",
            },
            {
                "icon": "👀",
                "title": "認人測驗",
                "description": "從成員特色與舞台線索練習辨認成員。",
                "text": "認人測驗",
            },
            {
                "icon": "✨",
                "title": "神圖抽卡",
                "description": "抽一張預先整理好的直拍或神圖連結。",
                "text": "神圖抽卡",
            },
        ],
    )


def _help_text() -> str:
    return (
        "📖 使用說明\n\n"
        "輸入：\n"
        "分析 aespa\n"
        "分析 IVE\n"
        "本週榜單\n"
        "互動專區\n"
        "每日一首\n\n"
        "目前支援：\n"
        "- 藝人分析報告\n"
        "- 本週 Bugs 榜單\n"
        "- 粉絲留言情緒分析\n"
        "- Play Zone 互動入口\n"
        "- 每日一首 K-pop 入口\n\n"
        "可分析藝人：\n"
        "aespa、IVE、BABYMONSTER、NMIXX、ILLIT、NCT、ZEROBASEONE、TXT、ENHYPEN、BOYNEXTDOOR"
    )


def welcome_text() -> str:
    return (
        "🇰🇷 歡迎來到 KPOP 補給站！🎶\n"
        "從入坑到深陷，我都陪你 ✨\n"
        "\n"
        "你可以這樣玩 ↓\n"
        "\n"
        "🔍 分析藝人\n"
        "└ 輸入「分析 aespa」看完整報告\n"
        "\n"
        "📊 本週榜單\n"
        "└ 看 Bugs 即時週榜 + 歷史週次\n"
        "\n"
        "🎮 互動專區\n"
        "└ 本命雷達、粉絲屬性、認人測驗、神圖抽卡\n"
        "\n"
        "🎧 每日一首\n"
        "└ 今日 MV、直拍、經典舞台一鍵推薦\n"
        "\n"
        "💡 AI 入坑\n"
        "└ 描述你的喜好，我幫你找到適合的團\n"
        "\n"
        "📮 我的口袋\n"
        "└ 把喜歡的 MV / 直拍 / 神圖通通收進來\n"
        "\n"
        "👇 直接點下方功能選單開始，\n"
        "或輸入「help」隨時查指令～\n"
        "祝你追星愉快！🎀"
    )


def is_artist_picker_request(message: str) -> bool:
    normalized = message.strip().casefold()
    return normalized in {"分析", "分析藝人", "選擇藝人", "artist", "藝人"}


def is_help_request(message: str) -> bool:
    return message.strip() in {"help", "Help", "HELP"}


def is_play_zone_request(message: str) -> bool:
    normalized = message.strip().casefold()
    return normalized in {
        "互動專區",
        "測驗",
        "k-pop play zone",
        "kpop play zone",
        "play zone",
        "playzone",
    }


def artist_picker_reply(context: MessageContext) -> Reply:
    return Reply(
        report="請輸入：分析 aespa、分析 IVE、分析 NCT",
        flex=_artist_picker_flex_contents(),
        alt_text="選擇要分析的 K-pop 藝人",
    )


def help_reply(context: MessageContext) -> Reply:
    return Reply(report=_help_text())


def play_zone_reply(context: MessageContext) -> Reply:
    return Reply(
        report="K-pop Play Zone",
        flex=_build_play_zone_flex_contents(),
        alt_text="K-pop Play Zone",
        fallback_text="請選擇：本命雷達測驗、粉絲屬性測驗、認人測驗、神圖抽卡",
    )


def fixed_command_help_reply(context: MessageContext) -> Reply:
    return Reply(report=_fixed_command_help_text())


def _fixed_command_help_text() -> str:
    return (
        "目前支援固定指令：\n"
        "1. 分析 aespa\n"
        "2. 分析 IVE\n"
        "3. 本週榜單\n"
        "4. 互動專區\n"
        "5. 每日一首\n"
        "6. 我的K-pop 口袋\n\n"
        "請用「分析 藝人名」取得完整報告。"
    )
