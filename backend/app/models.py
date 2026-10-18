"""ORM modellari: users, sessions, errors, progress, vocabulary.

Spetsifikatsiyadagi sxemaga qo'shimcha (nullable / default qiymatli) ustunlar:
- users.level_progress    — joriy darajadan keyingisigacha foiz (0-100)
- sessions.mode           — "free" (hands-free) yoki "ptt" (push-to-talk)
- sessions.level_at_start — sessiya boshidagi CEFR daraja
- sessions.summary        — keyingi sessiya konteksti uchun qisqa xulosa
- errors.explanation      — xatoning o'zbekcha izohi
- users.onboarded / explain_lang / speech_pace / goal / mic_mode / needs_placement — Adam sozlamalari
- users.plan / plan_expires_at / usage_* — tarif va vaqt limiti
- payments — chek orqali to'lovlar; bot_chats — Max egalarining guruh/kanallari
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

# SQLite faqat INTEGER PRIMARY KEY uchun autoincrement qiladi
BigIntPK = BigInteger().with_variant(Integer, "sqlite")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    first_name: Mapped[str] = mapped_column(String(128), default="")
    language: Mapped[str] = mapped_column(String(8), default="uz")
    cefr_level: Mapped[str] = mapped_column(String(2), default="A1")
    level_progress: Mapped[int] = mapped_column(SmallInteger, default=0)
    onboarded: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    explain_lang: Mapped[str] = mapped_column(String(8), default="uz", server_default="uz")
    speech_pace: Mapped[str] = mapped_column(String(8), default="slow", server_default="slow")
    goal: Mapped[str] = mapped_column(String(16), default="general", server_default="general")
    mic_mode: Mapped[str] = mapped_column(String(8), default="free", server_default="free")
    needs_placement: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_active_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    # Tarif: free | pro | max
    plan: Mapped[str] = mapped_column(String(8), default="free", server_default="free")
    plan_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    plan_reminded: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    # Limit oynasi: birinchi foydalanishdan boshlanadi, oyna tugaganda nolga qaytadi
    usage_window_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    usage_seconds: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    limit_notify: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")


class Payment(Base):
    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    plan: Mapped[str] = mapped_column(String(8))
    amount: Mapped[int] = mapped_column(Integer)
    # awaiting_receipt | checking | review | approved | rejected
    status: Mapped[str] = mapped_column(String(16), default="awaiting_receipt", index=True)
    file_id: Mapped[str | None] = mapped_column(String(256), nullable=True)
    image_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    transaction_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    analysis: Mapped[str | None] = mapped_column(Text, nullable=True)
    decision_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    decided_by: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class BotChat(Base):
    """Bot qo'shilgan guruh yoki kanal (faqat Max egalari uchun ishlaydi)."""

    __tablename__ = "bot_chats"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    chat_type: Mapped[str] = mapped_column(String(16))
    title: Mapped[str] = mapped_column(String(256), default="")
    owner_user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1")
    daily_lessons: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1")
    last_lesson_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    notice_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Session(Base):
    __tablename__ = "sessions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sentences_spoken: Mapped[int] = mapped_column(Integer, default=0)
    words_spoken: Mapped[int] = mapped_column(Integer, default=0)
    fluency_score: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    grammar_score: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    pronunciation_score: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    comprehension_score: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    mode: Mapped[str] = mapped_column(String(8), default="free")
    level_at_start: Mapped[str] = mapped_column(String(2), default="A1")
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)


class Error(Base):
    __tablename__ = "errors"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    session_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sessions.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    error_type: Mapped[str] = mapped_column(String(16))
    wrong_text: Mapped[str] = mapped_column(Text)
    correct_text: Mapped[str] = mapped_column(Text)
    severity: Mapped[str] = mapped_column(String(8), default="medium")
    explanation: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class Progress(Base):
    __tablename__ = "progress"
    __table_args__ = (UniqueConstraint("user_id", "date", name="uq_progress_user_date"),)

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    date: Mapped[date] = mapped_column(Date)
    sessions_count: Mapped[int] = mapped_column(Integer, default=0)
    total_sentences: Mapped[int] = mapped_column(Integer, default=0)
    total_words: Mapped[int] = mapped_column(Integer, default=0)
    cefr_level: Mapped[str] = mapped_column(String(2), default="A1")


class Vocabulary(Base):
    __tablename__ = "vocabulary"
    __table_args__ = (UniqueConstraint("user_id", "word", name="uq_vocabulary_user_word"),)

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    word: Mapped[str] = mapped_column(String(64))
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    times_used: Mapped[int] = mapped_column(Integer, default=1)
