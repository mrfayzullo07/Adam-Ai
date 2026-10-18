"""Pydantic sxemalar: API javoblari va Telegram foydalanuvchi ma'lumotlari."""
from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

CefrLevel = Literal["A1", "A2", "B1", "B2", "C1", "C2"]
ExplainLang = Literal["uz", "mix", "en"]
SpeechPace = Literal["slow", "normal"]
Goal = Literal["general", "travel", "work", "ielts"]
MicMode = Literal["free", "ptt"]


class TelegramUser(BaseModel):
    """initData ichidagi `user` maydoni."""

    id: int
    first_name: str = ""
    last_name: str | None = None
    username: str | None = None
    language_code: str | None = None


class LevelInfo(BaseModel):
    level: str
    next_level: str | None
    progress: int = Field(ge=0, le=100)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    telegram_id: int
    username: str | None
    first_name: str
    language: str
    cefr_level: str
    level_progress: int
    onboarded: bool
    explain_lang: str
    speech_pace: str
    goal: str
    mic_mode: str
    needs_placement: bool
    created_at: datetime


class PlanInfo(BaseModel):
    """Joriy tarif va vaqt limiti holati."""

    plan: str
    plan_title: str
    plan_expires_at: datetime | None
    limit_seconds: int | None
    window_hours: int | None
    used_seconds: int
    remaining_seconds: int | None
    resets_at: datetime | None


class PlanCatalogItem(BaseModel):
    code: str
    title: str
    price: int
    limit_seconds: int | None
    window_hours: int | None
    groups: bool


class PlansResponse(BaseModel):
    plans: list[PlanCatalogItem]
    plan_days: int
    bot_username: str | None
    current: PlanInfo


class SettingsIn(BaseModel):
    """Sozlamalarni qisman yangilash: faqat yuborilgan maydonlar o'zgaradi."""

    cefr_level: CefrLevel | None = None
    explain_lang: ExplainLang | None = None
    speech_pace: SpeechPace | None = None
    goal: Goal | None = None
    mic_mode: MicMode | None = None
    needs_placement: bool | None = None
    onboarded: bool | None = None


class SessionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    started_at: datetime
    ended_at: datetime | None
    duration_seconds: int | None
    sentences_spoken: int
    words_spoken: int
    fluency_score: int | None
    grammar_score: int | None
    pronunciation_score: int | None
    comprehension_score: int | None
    mode: str
    level_at_start: str
    summary: str | None


class ErrorOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    session_id: uuid.UUID
    error_type: str
    wrong_text: str
    correct_text: str
    severity: str
    explanation: str | None
    created_at: datetime


class ErrorsResponse(BaseModel):
    items: list[ErrorOut]
    by_type: dict[str, int]
    by_severity: dict[str, int]


class VocabularyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    word: str
    first_seen_at: datetime
    times_used: int


class DailyProgress(BaseModel):
    date: date
    sessions_count: int
    total_sentences: int
    total_words: int
    cefr_level: str


class ProgressResponse(BaseModel):
    level: LevelInfo
    streak_days: int
    days: list[DailyProgress]
    totals: dict[str, int]
    average_scores: dict[str, float | None]


class MeResponse(BaseModel):
    user: UserOut
    level: LevelInfo
    streak_days: int
    today: DailyProgress | None
    last_session: SessionOut | None
    plan: PlanInfo
