"""Gemini function declarations va tool_call handler.

Har bir tool chaqiruvi:
  1) argumentlarni validatsiya qiladi / chegaralaydi,
  2) kerak bo'lsa DB ga yozadi,
  3) Gemini'ga qaytariladigan javobni va client'ga yuboriladigan real-time eventlarni qaytaradi.
"""
from __future__ import annotations

import logging
import math
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from google.genai import types
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User
from app.services import level as lvl
from app.services.session_service import (
    ERROR_TYPES,
    SCORE_KEYS,
    SEVERITIES,
    SessionState,
    save_error,
    upsert_vocabulary,
)

logger = logging.getLogger(__name__)

DbFactory = Callable[[], AsyncSession]

_S = types.Schema
_T = types.Type

LOG_ERROR = types.FunctionDeclaration(
    name="log_error",
    description=(
        "Record a learner mistake that you just corrected out loud. Call it EVERY time you correct "
        "grammar, pronunciation or vocabulary. Call silently."
    ),
    parameters=_S(
        type=_T.OBJECT,
        properties={
            "error_type": _S(type=_T.STRING, enum=sorted(ERROR_TYPES), description="Category of the mistake."),
            "wrong": _S(type=_T.STRING, description="Exact wrong fragment the learner said (short)."),
            "correct": _S(type=_T.STRING, description="Correct English version."),
            "severity": _S(type=_T.STRING, enum=["low", "medium", "high"], description="How serious the mistake is."),
            "explanation_uz": _S(type=_T.STRING, description="One short explanation in Uzbek (Latin)."),
        },
        required=["error_type", "wrong", "correct", "severity"],
    ),
)

UPDATE_SCORES = types.FunctionDeclaration(
    name="update_scores",
    description=(
        "Update the learner's current performance scores (1-5, relative to their CEFR level). "
        "Call after about every 4-5 learner turns and near the end. Call silently."
    ),
    parameters=_S(
        type=_T.OBJECT,
        properties={k: _S(type=_T.INTEGER, description=f"{k} score 1-5") for k in SCORE_KEYS},
        required=list(SCORE_KEYS),
    ),
)

RECORD_VOCABULARY = types.FunctionDeclaration(
    name="record_vocabulary",
    description=(
        "Record an English word or short phrase the learner correctly used on their own "
        "(not just repeated). Lowercase base form. Call silently."
    ),
    parameters=_S(
        type=_T.OBJECT,
        properties={"word": _S(type=_T.STRING, description="English word or short phrase, lowercase.")},
        required=["word"],
    ),
)

SUGGEST_LEVEL = types.FunctionDeclaration(
    name="suggest_level",
    description=(
        "Recommend a different CEFR level when you are fairly confident the learner is consistently "
        "above or below their current level. The system makes the final decision. Call silently."
    ),
    parameters=_S(
        type=_T.OBJECT,
        properties={
            "level": _S(type=_T.STRING, enum=list(lvl.CEFR_LEVELS), description="Recommended CEFR level."),
            "reason": _S(type=_T.STRING, description="Short reason in Uzbek."),
        },
        required=["level", "reason"],
    ),
)

SET_LEVEL = types.FunctionDeclaration(
    name="set_level",
    description=(
        "Set the learner's CEFR level at the END of a placement test. Use only when the placement "
        "test is required in this session. Call silently, then tell the learner the result in Uzbek."
    ),
    parameters=_S(
        type=_T.OBJECT,
        properties={
            "level": _S(type=_T.STRING, enum=list(lvl.CEFR_LEVELS), description="Placement result."),
            "reason": _S(
                type=_T.STRING,
                description="One short sentence WRITTEN IN UZBEK (Latin script), shown to the learner. Not English.",
            ),
        },
        required=["level"],
    ),
)

TOOL_DECLARATIONS: list[types.FunctionDeclaration] = [
    LOG_ERROR,
    UPDATE_SCORES,
    RECORD_VOCABULARY,
    SUGGEST_LEVEL,
    SET_LEVEL,
]

# Adam gapirayotganda to'xtamasin: BLOCKING tool javobidan keyin model yangi navbat boshlab,
# hozirgina aytgan gapini takrorlab yuboradi. NON_BLOCKING + SILENT javob buni oldini oladi.
for _decl in TOOL_DECLARATIONS:
    _decl.behavior = types.Behavior.NON_BLOCKING

# Javobidan keyin Adam gapirishi kerak bo'lgan tool'lar (natijani foydalanuvchiga aytadi)
SPEAK_AFTER_TOOLS = {"set_level"}


def response_scheduling(name: str) -> types.FunctionResponseScheduling:
    if name in SPEAK_AFTER_TOOLS:
        return types.FunctionResponseScheduling.WHEN_IDLE
    return types.FunctionResponseScheduling.SILENT


def get_tools() -> list[types.Tool]:
    return [types.Tool(function_declarations=TOOL_DECLARATIONS)]


@dataclass(slots=True)
class ToolResult:
    """Gemini'ga qaytadigan javob + client'ga yuboriladigan eventlar."""

    response: dict[str, Any]
    events: list[dict[str, Any]] = field(default_factory=list)


def _clean_text(value: Any, limit: int) -> str:
    return " ".join(str(value or "").split())[:limit]


def _clamp_score(value: Any) -> int | None:
    try:
        return max(1, min(5, math.floor(float(value) + 0.5)))
    except (TypeError, ValueError):
        return None


async def _log_error(args: dict[str, Any], state: SessionState, db_factory: DbFactory) -> ToolResult:
    error_type = _clean_text(args.get("error_type"), 16).lower()
    if error_type not in ERROR_TYPES:
        error_type = "grammar"
    severity = _clean_text(args.get("severity"), 8).lower()
    if severity not in SEVERITIES:
        severity = "medium"
    wrong = _clean_text(args.get("wrong"), 300)
    correct = _clean_text(args.get("correct"), 300)
    explanation = _clean_text(args.get("explanation_uz"), 400) or None
    if not wrong or not correct:
        return ToolResult(response={"result": "ignored", "reason": "wrong and correct are required"})

    async with db_factory() as db:
        err = await save_error(
            db, state, error_type=error_type, wrong=wrong, correct=correct, severity=severity, explanation=explanation
        )
    state.error_severities.append(severity)
    state.errors_logged.append({"wrong": wrong, "correct": correct, "type": error_type})
    event = {
        "type": "error",
        "id": err.id,
        "error_type": error_type,
        "wrong": wrong,
        "correct": correct,
        "severity": severity,
        "explanation": explanation,
    }
    return ToolResult(response={"result": "ok"}, events=[event])


async def _update_scores(args: dict[str, Any], state: SessionState, _: DbFactory) -> ToolResult:
    scores = {k: s for k in SCORE_KEYS if (s := _clamp_score(args.get(k))) is not None}
    if not scores:
        return ToolResult(response={"result": "ignored", "reason": "no valid scores"})
    state.score_updates.append(scores)
    events = [{"type": "scores", **state.final_scores(), "latest": scores}, state.level_event()]
    return ToolResult(response={"result": "ok"}, events=events)


async def _record_vocabulary(args: dict[str, Any], state: SessionState, db_factory: DbFactory) -> ToolResult:
    word = _clean_text(args.get("word"), 64).lower().strip(" .,!?;:\"")
    if not word or not any(c.isalpha() for c in word):
        return ToolResult(response={"result": "ignored"})
    async with db_factory() as db:
        vocab, is_new = await upsert_vocabulary(db, state.user_id, word)
    if word not in state.vocabulary:
        state.vocabulary.append(word)
    event = {"type": "vocabulary", "word": word, "is_new": is_new, "times_used": vocab.times_used}
    return ToolResult(response={"result": "ok"}, events=[event])


async def _suggest_level(args: dict[str, Any], state: SessionState, _: DbFactory) -> ToolResult:
    raw = _clean_text(args.get("level"), 4).upper()
    if raw not in lvl.CEFR_LEVELS:
        return ToolResult(response={"result": "ignored", "reason": "invalid level"})
    state.suggested_level = raw
    state.suggested_reason = _clean_text(args.get("reason"), 300) or None
    return ToolResult(
        response={"result": "noted", "note": "Final level is decided by the system after the session."},
        events=[state.level_event()],
    )


async def _set_level(args: dict[str, Any], state: SessionState, db_factory: DbFactory) -> ToolResult:
    if not state.placement:
        return ToolResult(response={"result": "ignored", "reason": "no placement test in this session; use suggest_level"})
    level = _clean_text(args.get("level"), 4).upper()
    if level not in lvl.CEFR_LEVELS:
        return ToolResult(response={"result": "ignored", "reason": "invalid level"})
    reason = _clean_text(args.get("reason"), 300) or None
    async with db_factory() as db:
        user = await db.get(User, state.user_id)
        if user is not None:
            user.cefr_level = level
            user.level_progress = 0
            user.needs_placement = False
            await db.commit()
    state.level = level
    state.level_progress = 0
    state.placement_done = True
    event = {
        "type": "placement_result",
        "level": level,
        "next_level": lvl.next_level(level),
        "progress": 0,
        "reason": reason,
    }
    return ToolResult(
        response={"result": "ok", "note": f"Level saved as {level}. Tell the learner in Uzbek and continue at {level}."},
        events=[event],
    )


_HANDLERS = {
    "log_error": _log_error,
    "update_scores": _update_scores,
    "record_vocabulary": _record_vocabulary,
    "suggest_level": _suggest_level,
    "set_level": _set_level,
}


async def handle_function_call(
    name: str, args: dict[str, Any] | None, state: SessionState, db_factory: DbFactory
) -> ToolResult:
    """Tool chaqiruvini bajaradi. Hech qachon exception tashlamaydi — Gemini doim javob oladi."""
    handler = _HANDLERS.get(name)
    if handler is None:
        logger.warning("Noma'lum tool: %s", name)
        return ToolResult(response={"error": f"unknown function {name}"})
    try:
        return await handler(dict(args or {}), state, db_factory)
    except Exception:  # noqa: BLE001
        logger.exception("Tool '%s' bajarilishida xato", name)
        return ToolResult(response={"error": "internal error, continue the lesson"})
