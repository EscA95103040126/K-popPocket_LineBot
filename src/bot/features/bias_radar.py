from __future__ import annotations

import json
import random
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import quote

from flask import request

from src.bot.dispatcher import MessageContext
from src.bot.flex_common import (
    PLAY_ZONE_ACCENT_COLOR,
    PLAY_ZONE_BODY_COLOR,
    PLAY_ZONE_MUTED_TEXT_COLOR,
    PLAY_ZONE_SUBTITLE_COLOR,
    PLAY_ZONE_TEXT_COLOR,
)
from src.bot.reply import Reply
from src.bot.text_utils import safe_float, split_bias_radar_tags

if TYPE_CHECKING:
    from src.bot.catalog import PlayZoneCatalog


BIAS_RADAR_TRIGGERS = {"本命雷達測驗", "本命雷達", "測本命"}
BIAS_RADAR_IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp")
BIAS_RADAR_SESSION_TTL_SECONDS = 60 * 30
BIAS_RADAR_SESSION_MAX_SIZE = 500


def _bias_radar_option_button(question_index: int, option: str) -> dict:
    return {
        "type": "box",
        "layout": "vertical",
        "paddingAll": "12px",
        "backgroundColor": "#FFFFFF",
        "cornerRadius": "8px",
        "action": {
            "type": "postback",
            "data": f"本命雷達:{question_index}:{option}",
        },
        "contents": [
            {
                "type": "text",
                "text": option,
                "size": "md",
                "weight": "bold",
                "color": PLAY_ZONE_ACCENT_COLOR,
            },
        ],
    }


def _score_bias_radar_member(
    member: dict[str, str],
    answers: list[str],
) -> tuple[int, dict[str, str], list[str]]:
    score = 0
    matched: list[str] = []
    gender_answer, appearance_answer, position_answer, vibe_answer, relationship_answer = answers

    if _bias_radar_gender_matches(member, gender_answer):
        score += 3

    for field, answer in (
        ("appearance", appearance_answer),
        ("position", position_answer),
        ("vibe", vibe_answer),
        ("relationship", relationship_answer),
    ):
        if answer in split_bias_radar_tags(member.get(field, "")):
            score += 2
            matched.append(answer)

    return score, member, matched


def _bias_radar_gender_matches(member: dict[str, str], answer: str) -> bool:
    group_type = member.get("group_type", "").strip()
    gender_group = member.get("gender_group", "").strip()
    if answer == "都可以":
        return True
    if answer == "男團":
        return group_type == "boy_group" or gender_group == "male"
    if answer == "女團":
        return group_type == "girl_group" or gender_group == "female"
    return False


def is_bias_radar_command(message: str) -> bool:
    normalized = message.strip()
    return normalized in BIAS_RADAR_TRIGGERS or normalized.startswith("本命雷達:")


def safe_bias_radar_image_filename(filename: str) -> str | None:
    normalized = filename.strip().replace("\\", "/")
    path = Path(normalized)
    if not normalized or "/" in normalized or path.name != normalized:
        return None
    if path.suffix.casefold() not in BIAS_RADAR_IMAGE_EXTENSIONS:
        return None
    return normalized


def _bias_radar_group_type_label(member: dict[str, str]) -> str:
    labels = {
        "boy_group": "男團",
        "girl_group": "女團",
        "solo": "solo",
        "mixed_group": "混合團",
    }
    return labels.get(member.get("group_type", "").strip(), "未分類")


def _bias_radar_reason(
    recommendation: dict[str, str],
    answers: list[str],
    matched: list[str],
) -> str:
    _, appearance_answer, position_answer, vibe_answer, relationship_answer = answers
    focus_tags = matched or [appearance_answer, position_answer, vibe_answer, relationship_answer]
    focus_text = "、".join(focus_tags[:3])
    return (
        f"你偏好{focus_text}的本命型，所以推薦你關注 "
        f"{recommendation['artist']} {recommendation['member']}。"
    )


def _format_bias_radar_result_text(result: dict) -> str:
    recommendation = result["recommendation"]
    return "\n".join(
        [
            "你的本命雷達結果",
            f"推薦：{recommendation['artist']} {recommendation['member']}",
            f"類型：{_bias_radar_group_type_label(recommendation)}",
            f"命中標籤：{result['matched_label_text']}",
            result["reason"],
            recommendation["url"],
        ]
    )


class BiasRadarFeature:
    """Five-question bias radar quiz; keeps each user's progress for 30 minutes."""

    def __init__(
        self,
        catalog: PlayZoneCatalog,
        rng: random.Random,
        clock: Callable[[], float],
    ) -> None:
        self.catalog = catalog
        self.rng = rng
        self.clock = clock
        self.bias_radar_sessions: dict[str, dict[str, object]] = {}

    def _build_bias_radar_question_flex_contents(self, question_index: int) -> dict:
        questions = self._load_bias_radar_questions()
        question = questions[question_index]
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
                        "text": "本命雷達測驗",
                        "size": "xs",
                        "color": PLAY_ZONE_SUBTITLE_COLOR,
                    },
                    {
                        "type": "text",
                        "text": f"Q{question_number}/{len(questions)}",
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
                        _bias_radar_option_button(question_index, option)
                        for option in question["options"]
                    ],
                ],
            },
        }

    def _build_bias_radar_result_flex_contents(self, result: dict) -> dict:
        recommendation = result["recommendation"]
        bubble = {
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
                        "text": "你的本命雷達結果",
                        "size": "xs",
                        "color": PLAY_ZONE_SUBTITLE_COLOR,
                    },
                    {
                        "type": "text",
                        "text": f"{recommendation['artist']} {recommendation['member']}",
                        "size": "xl",
                        "weight": "bold",
                        "color": "#FFFFFF",
                        "margin": "sm",
                        "wrap": True,
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
                        "text": f"類型：{_bias_radar_group_type_label(recommendation)}",
                        "size": "sm",
                        "color": PLAY_ZONE_TEXT_COLOR,
                        "wrap": True,
                    },
                    {
                        "type": "text",
                        "text": f"命中標籤：{result['matched_label_text']}",
                        "size": "sm",
                        "color": PLAY_ZONE_TEXT_COLOR,
                        "wrap": True,
                    },
                    {
                        "type": "text",
                        "text": result["reason"],
                        "size": "sm",
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
                            "text": "本命雷達測驗",
                        },
                    },
                    {
                        "type": "button",
                        "style": "secondary",
                        "height": "sm",
                        "action": {
                            "type": "message",
                            "label": "回 Play Zone",
                            "text": "互動專區",
                        },
                    },
                ],
            },
        }
        image_url = self._bias_radar_image_url(recommendation)
        if image_url:
            bubble["hero"] = {
                "type": "image",
                "url": image_url,
                "size": "full",
                "aspectRatio": "20:13",
                "aspectMode": "fit",
            }
        return bubble

    def is_bias_radar_quiz_request(self, message: str, user_id: str = "analyze-user") -> bool:
        self._prune_bias_radar_sessions()
        return is_bias_radar_command(message) or user_id in self.bias_radar_sessions

    def bias_radar_reply(self, context: MessageContext) -> Reply:
        response = self._bias_radar_quiz_response(context.user_id, context.text)
        return Reply(report=response["report"], flex=response["flex"], alt_text="本命雷達測驗")

    def _bias_radar_quiz_response(self, user_id: str, message: str) -> dict:
        normalized = message.strip()
        questions = self._load_bias_radar_questions()
        self._prune_bias_radar_sessions()
        if normalized in BIAS_RADAR_TRIGGERS:
            self._store_bias_radar_session(user_id, question_index=0, answers=[])
            return {
                "report": self._bias_radar_question_text(0),
                "flex": self._build_bias_radar_question_flex_contents(0),
            }

        session = self.bias_radar_sessions.get(user_id)
        if not session:
            self._store_bias_radar_session(user_id, question_index=0, answers=[])
            return {
                "report": self._bias_radar_question_text(0),
                "flex": self._build_bias_radar_question_flex_contents(0),
            }

        question_index = int(session.get("question_index", 0))
        option = self._bias_radar_answer_from_message(normalized, question_index)
        if option is None:
            return {
                "report": self._bias_radar_question_text(question_index),
                "flex": self._build_bias_radar_question_flex_contents(question_index),
            }

        answers = [str(answer) for answer in session.get("answers", [])]
        answers.append(option)
        question_index += 1
        if question_index < len(questions):
            self._store_bias_radar_session(user_id, question_index=question_index, answers=answers)
            return {
                "report": self._bias_radar_question_text(question_index),
                "flex": self._build_bias_radar_question_flex_contents(question_index),
            }

        self.bias_radar_sessions.pop(user_id, None)
        result = self._score_bias_radar_result(answers)
        return {
            "report": _format_bias_radar_result_text(result),
            "flex": self._build_bias_radar_result_flex_contents(result),
        }

    def _store_bias_radar_session(self, user_id: str, question_index: int, answers: list[str]) -> None:
        self.bias_radar_sessions[user_id] = {
            "question_index": question_index,
            "answers": answers,
            "updated_at": self.clock(),
        }
        self._trim_bias_radar_sessions()

    def _prune_bias_radar_sessions(self, now: float | None = None) -> None:
        current_time = now if now is not None else self.clock()
        expired_user_ids = [
            user_id
            for user_id, session in self.bias_radar_sessions.items()
            if current_time - self._session_updated_at(session) > BIAS_RADAR_SESSION_TTL_SECONDS
        ]
        for user_id in expired_user_ids:
            self.bias_radar_sessions.pop(user_id, None)

    def _trim_bias_radar_sessions(self) -> None:
        while len(self.bias_radar_sessions) > BIAS_RADAR_SESSION_MAX_SIZE:
            oldest_user_id = min(
                self.bias_radar_sessions,
                key=lambda user_id: self._session_updated_at(self.bias_radar_sessions[user_id]),
            )
            self.bias_radar_sessions.pop(oldest_user_id, None)

    def _session_updated_at(self, session: dict[str, object]) -> float:
        updated_at = safe_float(session.get("updated_at"))
        return updated_at or self.clock()

    def _bias_radar_answer_from_message(self, message: str, question_index: int) -> str | None:
        questions = self._load_bias_radar_questions()
        if question_index >= len(questions):
            return None
        options = questions[question_index]["options"]

        if message.startswith("本命雷達:"):
            parts = message.split(":", 2)
            if len(parts) != 3:
                return None
            try:
                action_question_index = int(parts[1])
            except ValueError:
                return None
            if action_question_index != question_index:
                return None
            option = parts[2].strip()
        else:
            option = message.strip()

        if option in options:
            return option
        return None

    def _bias_radar_question_text(self, question_index: int) -> str:
        questions = self._load_bias_radar_questions()
        question_number = question_index + 1
        return f"本命雷達測驗 Q{question_number}/{len(questions)}：請在 LINE 卡片中選擇最符合你的答案。"

    def _load_bias_radar_questions(self) -> list[dict]:
        json_path = self.catalog.base_dir / "data" / "play_zone" / "bias_radar_questions.json"
        with json_path.open(encoding="utf-8") as file:
            questions = json.load(file)
        return questions if isinstance(questions, list) else []

    def _score_bias_radar_result(self, answers: list[str]) -> dict:
        members = self.catalog.load_bias_radar_members()
        if not members:
            raise ValueError("bias_radar_members.csv has no usable rows")

        scored_rows = [
            _score_bias_radar_member(member, answers)
            for member in members
        ]
        max_score = max(score for score, _, _ in scored_rows)
        top_matches = [
            (member, matched)
            for score, member, matched in scored_rows
            if score == max_score
        ]
        recommendation, matched = self.rng.choice(top_matches)
        matched_label_text = "、".join(matched) if matched else "整體氣質接近"
        return {
            "recommendation": recommendation,
            "matched": matched,
            "matched_label_text": matched_label_text,
            "score": max_score,
            "reason": _bias_radar_reason(recommendation, answers, matched),
        }

    def bias_radar_image_dir(self) -> Path:
        return self.catalog.base_dir / "data" / "play_zone" / "radar_image"

    def _bias_radar_image_path(self, member: dict[str, str]) -> Path | None:
        member_id = member.get("id", "").strip()
        if not member_id:
            return None
        image_dir = self.bias_radar_image_dir()
        for extension in BIAS_RADAR_IMAGE_EXTENSIONS:
            image_path = image_dir / f"{member_id}{extension}"
            if image_path.exists():
                return image_path
        return None

    def _bias_radar_image_url(self, member: dict[str, str]) -> str:
        image_path = self._bias_radar_image_path(member)
        if image_path is None:
            return ""
        filename = image_path.name
        forwarded_host = request.headers.get("X-Forwarded-Host", "").split(",", 1)[0].strip()
        forwarded_proto = request.headers.get("X-Forwarded-Proto", "").split(",", 1)[0].strip()
        host = forwarded_host or request.host
        scheme = forwarded_proto or request.scheme
        if host.endswith(".hf.space"):
            return (
                "https://huggingface.co/spaces/EscA95103040126/kpop-agent/resolve/main/"
                f"data/play_zone/radar_image/{quote(filename)}"
            )
        return f"{scheme}://{host}/play-zone/radar-image/{quote(filename)}"
