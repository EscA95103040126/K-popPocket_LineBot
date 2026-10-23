from __future__ import annotations

from src.bot.dispatcher import MessageContext
from src.bot.flex_common import (
    PLAY_ZONE_ACCENT_COLOR,
    PLAY_ZONE_BODY_COLOR,
    PLAY_ZONE_MUTED_TEXT_COLOR,
    PLAY_ZONE_SUBTITLE_COLOR,
    PLAY_ZONE_TEXT_COLOR,
)
from src.bot.reply import Reply

FAN_ATTRIBUTE_TYPES = {
    "group": {
        "name": "團飯",
        "tagline": "你喜歡的是整個團的化學反應。",
        "description": "你會看見每位成員在團體裡的角色，也享受舞台、團綜、互動與作品概念拼在一起的完整感。",
        "tip": "適合玩法：團體雷達、舞台名場面整理、全員魅力圖鑑。",
    },
    "solo": {
        "name": "唯飯",
        "tagline": "你有一位特別放在心尖上的本命。",
        "description": "你會優先追本命的直拍、造型、個人資源與成長瞬間，對細節記憶力很強，也很知道他的魅力在哪。",
        "tip": "適合玩法：本命雷達、直拍推薦、個人成長時間線。",
    },
    "trend": {
        "name": "跟風粉",
        "tagline": "你很會捕捉正在變紅的熱點。",
        "description": "你常被熱門舞台、短影音片段或社群討論吸引，喜歡先感受流行氛圍，再決定要不要深入入坑。",
        "tip": "適合玩法：熱門榜單、每日一首、神圖抽卡。",
    },
}
FAN_ATTRIBUTE_ORDER = ("group", "solo", "trend")
FAN_ATTRIBUTE_QUIZ = [
    {
        "question": "你通常是怎麼開始注意一個 K-pop 團？",
        "options": [
            {
                "label": "整團舞台很合",
                "description": "隊形、聲線和成員互動一起打到你。",
                "weights": {"group": 3, "solo": 1, "trend": 0},
            },
            {
                "label": "某位成員太亮眼",
                "description": "先被一個人吸住，才慢慢認識其他內容。",
                "weights": {"group": 0, "solo": 3, "trend": 1},
            },
            {
                "label": "大家都在討論",
                "description": "熱門片段、梗圖或榜單聲量讓你點進去看。",
                "weights": {"group": 1, "solo": 0, "trend": 3},
            },
        ],
    },
    {
        "question": "回歸期間，你最期待哪種內容？",
        "options": [
            {
                "label": "團體舞台",
                "description": "想看全員配置、走位和整體概念。",
                "weights": {"group": 3, "solo": 1, "trend": 0},
            },
            {
                "label": "本命直拍",
                "description": "先找自己最愛那位的鏡頭和造型。",
                "weights": {"group": 0, "solo": 3, "trend": 1},
            },
            {
                "label": "熱門精華",
                "description": "想先看社群上最紅、最多人轉的片段。",
                "weights": {"group": 1, "solo": 0, "trend": 3},
            },
        ],
    },
    {
        "question": "朋友問你推坑重點，你會先推薦？",
        "options": [
            {
                "label": "團綜或舞台",
                "description": "看完就懂這團的默契和定位。",
                "weights": {"group": 3, "solo": 0, "trend": 1},
            },
            {
                "label": "本命名場面",
                "description": "那個表情、那段高音或那支直拍不能錯過。",
                "weights": {"group": 1, "solo": 3, "trend": 0},
            },
            {
                "label": "爆紅短影片",
                "description": "先丟最容易懂、最有流量感的入門片段。",
                "weights": {"group": 0, "solo": 1, "trend": 3},
            },
        ],
    },
    {
        "question": "你整理收藏時，資料夾最可能怎麼分？",
        "options": [
            {
                "label": "團體時期",
                "description": "依回歸、舞台、團綜，把全員內容收好。",
                "weights": {"group": 3, "solo": 1, "trend": 0},
            },
            {
                "label": "本命專區",
                "description": "照片、直拍、訪談都先按同一位成員分類。",
                "weights": {"group": 0, "solo": 3, "trend": 1},
            },
            {
                "label": "最近熱門",
                "description": "先收現在最紅、最多人傳的內容。",
                "weights": {"group": 1, "solo": 0, "trend": 3},
            },
        ],
    },
    {
        "question": "你最容易被哪種瞬間再次圈住？",
        "options": [
            {
                "label": "全員默契爆發",
                "description": "舞台或互動讓你覺得少一個人都不行。",
                "weights": {"group": 3, "solo": 1, "trend": 0},
            },
            {
                "label": "本命神級鏡頭",
                "description": "一個眼神或一句話就足夠反覆重播。",
                "weights": {"group": 0, "solo": 3, "trend": 1},
            },
            {
                "label": "熱搜突然爆了",
                "description": "看到大家都在喊，會想立刻補課跟上。",
                "weights": {"group": 1, "solo": 0, "trend": 3},
            },
        ],
    },
]


def _build_fan_attribute_quiz_flex_contents(message: str) -> dict:
    quiz_state = _parse_fan_attribute_quiz_state(message)
    if quiz_state["is_result"]:
        return _build_fan_attribute_result_flex_contents(quiz_state["scores"])
    return _build_fan_attribute_question_flex_contents(
        quiz_state["question_index"],
        quiz_state["scores"],
    )


def _build_fan_attribute_question_flex_contents(
    question_index: int,
    scores: dict[str, int],
) -> dict:
    question = FAN_ATTRIBUTE_QUIZ[question_index]
    question_number = question_index + 1
    return {
        "type": "bubble",
        "size": "mega",
        "header": {
            "type": "box",
            "layout": "vertical",
            "backgroundColor": PLAY_ZONE_ACCENT_COLOR,
            "paddingAll": "18px",
            "contents": [
                {
                    "type": "text",
                    "text": "粉絲屬性測驗",
                    "size": "xs",
                    "color": PLAY_ZONE_SUBTITLE_COLOR,
                },
                {
                    "type": "text",
                    "text": f"Q{question_number}/5",
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
            "backgroundColor": PLAY_ZONE_BODY_COLOR,
            "paddingAll": "18px",
            "spacing": "md",
            "contents": [
                {
                    "type": "text",
                    "text": question["question"],
                    "size": "md",
                    "weight": "bold",
                    "color": PLAY_ZONE_TEXT_COLOR,
                    "wrap": True,
                },
                *[
                    _fan_attribute_option_button(question_index, scores, option)
                    for option in question["options"]
                ],
            ],
        },
    }


def _fan_attribute_option_button(
    question_index: int,
    scores: dict[str, int],
    option: dict,
) -> dict:
    next_scores = _add_fan_attribute_scores(scores, option["weights"])
    action_text = _fan_attribute_action_text(question_index + 1, next_scores)
    return {
        "type": "box",
        "layout": "vertical",
        "paddingAll": "12px",
        "backgroundColor": "#FFFFFF",
        "cornerRadius": "8px",
        "action": {"type": "postback", "data": action_text},
        "contents": [
            {
                "type": "text",
                "text": option["label"],
                "size": "md",
                "weight": "bold",
                "color": PLAY_ZONE_ACCENT_COLOR,
            },
            {
                "type": "text",
                "text": option["description"],
                "size": "xs",
                "color": PLAY_ZONE_MUTED_TEXT_COLOR,
                "wrap": True,
                "margin": "xs",
            },
        ],
    }


def _build_fan_attribute_result_flex_contents(scores: dict[str, int]) -> dict:
    fan_type_key = _fan_attribute_result_key(scores)
    fan_type = FAN_ATTRIBUTE_TYPES[fan_type_key]
    score_text = " / ".join(
        f"{FAN_ATTRIBUTE_TYPES[key]['name'].replace('粉絲', '')} {scores[key]}"
        for key in FAN_ATTRIBUTE_ORDER
    )
    return {
        "type": "bubble",
        "size": "mega",
        "header": {
            "type": "box",
            "layout": "vertical",
            "backgroundColor": PLAY_ZONE_ACCENT_COLOR,
            "paddingAll": "18px",
            "contents": [
                {
                    "type": "text",
                    "text": "你的粉絲屬性是",
                    "size": "xs",
                    "color": PLAY_ZONE_SUBTITLE_COLOR,
                },
                {
                    "type": "text",
                    "text": fan_type["name"],
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
            "backgroundColor": PLAY_ZONE_BODY_COLOR,
            "paddingAll": "18px",
            "spacing": "md",
            "contents": [
                {
                    "type": "text",
                    "text": fan_type["tagline"],
                    "size": "md",
                    "weight": "bold",
                    "color": PLAY_ZONE_TEXT_COLOR,
                    "wrap": True,
                },
                {
                    "type": "text",
                    "text": fan_type["description"],
                    "size": "sm",
                    "color": PLAY_ZONE_MUTED_TEXT_COLOR,
                    "wrap": True,
                },
                {
                    "type": "text",
                    "text": fan_type["tip"],
                    "size": "sm",
                    "color": PLAY_ZONE_ACCENT_COLOR,
                    "wrap": True,
                },
                {
                    "type": "text",
                    "text": f"分數：{score_text}",
                    "size": "xs",
                    "color": PLAY_ZONE_MUTED_TEXT_COLOR,
                    "wrap": True,
                },
                {
                    "type": "button",
                    "style": "primary",
                    "height": "sm",
                    "color": PLAY_ZONE_ACCENT_COLOR,
                    "action": {
                        "type": "message",
                        "label": "再測一次",
                        "text": "粉絲屬性測驗",
                    },
                },
            ],
        },
    }


def is_fan_attribute_quiz_request(message: str) -> bool:
    normalized = message.strip()
    return normalized == "粉絲屬性測驗" or normalized.startswith("粉絲屬性測驗:")


def fan_attribute_quiz_reply(context: MessageContext) -> Reply:
    return Reply(
        report=_fan_attribute_quiz_text(context.text),
        flex=_build_fan_attribute_quiz_flex_contents(context.text),
        alt_text="粉絲屬性測驗",
    )


def _parse_fan_attribute_quiz_state(message: str) -> dict:
    normalized = message.strip()
    empty_scores = {key: 0 for key in FAN_ATTRIBUTE_ORDER}
    if normalized == "粉絲屬性測驗":
        return {
            "question_index": 0,
            "scores": empty_scores,
            "is_result": False,
        }

    parts = normalized.split(":")
    if len(parts) != 3 or parts[0] != "粉絲屬性測驗":
        return {
            "question_index": 0,
            "scores": empty_scores,
            "is_result": False,
        }

    scores = _decode_fan_attribute_scores(parts[2])
    if parts[1] == "result":
        return {
            "question_index": len(FAN_ATTRIBUTE_QUIZ),
            "scores": scores,
            "is_result": True,
        }

    try:
        question_index = int(parts[1])
    except ValueError:
        question_index = 0

    if question_index >= len(FAN_ATTRIBUTE_QUIZ):
        return {
            "question_index": len(FAN_ATTRIBUTE_QUIZ),
            "scores": scores,
            "is_result": True,
        }
    if question_index < 0:
        question_index = 0

    return {
        "question_index": question_index,
        "scores": scores,
        "is_result": False,
    }


def _decode_fan_attribute_scores(encoded_scores: str) -> dict[str, int]:
    values = encoded_scores.split(",")
    scores = {}
    for index, key in enumerate(FAN_ATTRIBUTE_ORDER):
        try:
            scores[key] = int(values[index])
        except (IndexError, ValueError):
            scores[key] = 0
    return scores


def _add_fan_attribute_scores(
    scores: dict[str, int],
    weights: dict[str, int],
) -> dict[str, int]:
    return {
        key: scores.get(key, 0) + weights.get(key, 0)
        for key in FAN_ATTRIBUTE_ORDER
    }


def _fan_attribute_action_text(question_index: int, scores: dict[str, int]) -> str:
    encoded_scores = ",".join(str(scores[key]) for key in FAN_ATTRIBUTE_ORDER)
    if question_index >= len(FAN_ATTRIBUTE_QUIZ):
        return f"粉絲屬性測驗:result:{encoded_scores}"
    return f"粉絲屬性測驗:{question_index}:{encoded_scores}"


def _fan_attribute_result_key(scores: dict[str, int]) -> str:
    return max(
        FAN_ATTRIBUTE_ORDER,
        key=lambda key: (scores.get(key, 0), -FAN_ATTRIBUTE_ORDER.index(key)),
    )


def _fan_attribute_quiz_text(message: str) -> str:
    quiz_state = _parse_fan_attribute_quiz_state(message)
    if not quiz_state["is_result"]:
        question_number = quiz_state["question_index"] + 1
        return f"粉絲屬性測驗 Q{question_number}/5：請在 LINE 卡片中選擇最符合你的答案。"

    scores = quiz_state["scores"]
    fan_type = FAN_ATTRIBUTE_TYPES[_fan_attribute_result_key(scores)]
    score_text = " / ".join(
        f"{FAN_ATTRIBUTE_TYPES[key]['name']} {scores[key]}"
        for key in FAN_ATTRIBUTE_ORDER
    )
    return (
        f"你的粉絲屬性是：{fan_type['name']}\n"
        f"{fan_type['tagline']}\n"
        f"{fan_type['description']}\n"
        f"{fan_type['tip']}\n"
        f"分數：{score_text}"
    )
