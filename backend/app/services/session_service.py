"""Sessiya hayot sikli: yaratish, kontekst yuklash, real-time yozuvlar va yakunlash."""
from __future__ import annotations

import logging
import math
import re
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.gemini.prompt import ErrorContext
from app.models import Error, Progress, Session, User, Vocabulary, utcnow
from app.services import level as lvl

logger = logging.getLogger(__name__)

SCORE_KEYS: tuple[str, ...] = ("fluency", "grammar", "pronunciation", "comprehension")
ERROR_TYPES: frozenset[str] = frozenset({"grammar", "pronunciation", "vocabulary"})
SEVERITIES: frozenset[str] = frozenset({"low", "medium", "high"})

_WORD_RE = re.compile(r"[A-Za-z\u2019'’ʻʼ\-]+")
_UZ_MARKERS = re.compile(r"[oOgG][\u2019'’ʻʼ`]")
_UZ_STOPWORDS = frozenset(
    """
    va bu u men sen siz biz ular nima qanday qachon qayer qayerda nega kerak emas edi bor yo'q
    yaxshi rahmat salom assalomu alaykum ha yoq yo'q endi keyin oldin uchun bilan lekin ammo
    mening sizning bilmayman tushunmadim iltimos qiling ayting takrorlang zo'r barakalla men ham
    qilaman boraman keldim ketdim bugun ertaga kecha ism ismim yoshim nechchi qancha bitta ikki
    """.split()
)


def english_word_count(text: str) -> int:
    """Matndagi inglizcha so'zlar sonini taxminiy hisoblaydi (o'zbekcha so'zlar chiqarib tashlanadi)."""
    count = 0
    for word in _WORD_RE.findall(text):
        w = word.lower().strip("'’-")
        if not w or _UZ_MARKERS.search(word) or w in _UZ_STOPWORDS:
            continue
        count += 1
    return count


def as_utc(dt: datetime | None) -> datetime | None:
    """SQLite naive datetime qaytaradi — UTC deb hisoblaymiz."""
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


@dataclass
class SessionState:
    """Bitta jonli sessiyaning xotiradagi holati."""

    session_id: uuid.UUID
    user_id: int
    user_name: str
    level: str
    level_progress: int
    mode: str
    started_at: datetime = field(default_factory=utcnow)
    score_updates: list[dict[str, int]] = field(default_factory=list)
    error_severities: list[str] = field(default_factory=list)
    errors_logged: list[dict[str, str]] = field(default_factory=list)
    suggested_level: str | None = None
    suggested_reason: str | None = None
    vocabulary: list[str] = field(default_factory=list)
    sentences_spoken: int = 0
    words_spoken: int = 0
    user_buffer: str = ""
    recent_lines: deque[tuple[str, str]] = field(default_factory=lambda: deque(maxlen=6))
    finalized: bool = False
    placement: bool = False
    placement_done: bool = False

    def __post_init__(self) -> None:
        self.started_at = as_utc(self.started_at) or utcnow()

    # ---------- transkript ----------
    def add_user_transcript(self, text: str) -> None:
        self.user_buffer += text

    def flush_user_turn(self) -> str:
        """Foydalanuvchi navbati tugaganda gap/so'z statistikasini yangilaydi."""
        utterance = " ".join(self.user_buffer.split())
        self.user_buffer = ""
        if not utterance:
            return ""
        words = english_word_count(utterance)
        if words:
            self.sentences_spoken += 1
            self.words_spoken += words
        self.recent_lines.append(("user", utterance[:200]))
        return utterance

    def add_adam_line(self, text: str) -> None:
        text = " ".join(text.split())
        if text:
            self.recent_lines.append(("adam", text[:200]))

    # ---------- skorlar ----------
    def final_scores(self) -> dict[str, int | None]:
        if not self.score_updates:
            return {k: None for k in SCORE_KEYS}
        result: dict[str, int | None] = {}
        for key in SCORE_KEYS:
            vals = [u[key] for u in self.score_updates if key in u]
            result[key] = math.floor(sum(vals) / len(vals) + 0.5) if vals else None
        return result

    def elapsed_seconds(self) -> int:
        return max(0, int((utcnow() - self.started_at).total_seconds()))

    def projection(self) -> lvl.LevelResult:
        return lvl.project_level(
            level=self.level,
            progress=self.level_progress,
            scores=self.final_scores(),
            duration_seconds=self.elapsed_seconds(),
            error_severities=self.error_severities,
            suggested_level=self.suggested_level,
        )

    def level_event(self, result: lvl.LevelResult | None = None, final: bool = False) -> dict[str, Any]:
        result = result or self.projection()
        return {
            "type": "level_update",
            "level": result.level,
            "next_level": lvl.next_level(result.level),
            "progress": result.progress,
            "gain": round(result.gain, 1),
            "leveled_up": result.leveled_up,
            "final": final,
        }


# ------------------------------------------------------------------ DB amallar

async def create_session(db: AsyncSession, user: User, mode: str) -> Session:
    session = Session(user_id=user.id, started_at=utcnow(), mode=mode, level_at_start=lvl.normalize_level(user.cefr_level))
    db.add(session)
    user.last_active_at = utcnow()
    await db.commit()
    await db.refresh(session)
    return session


async def load_user_context(db: AsyncSession, user_id: int) -> tuple[list[ErrorContext], str | None]:
    """Oxirgi 5 ta xato va oxirgi tugallangan sessiya xulosasi."""
    rows = (
        await db.execute(
            select(Error.error_type, Error.wrong_text, Error.correct_text)
            .where(Error.user_id == user_id)
            .order_by(Error.created_at.desc(), Error.id.desc())
            .limit(5)
        )
    ).all()
    errors = [ErrorContext(error_type=r[0], wrong_text=r[1], correct_text=r[2]) for r in rows]
    summary = (
        await db.execute(
            select(Session.summary)
            .where(Session.user_id == user_id, Session.ended_at.is_not(None), Session.summary.is_not(None))
            .order_by(Session.ended_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    return errors, summary


async def save_error(
    db: AsyncSession,
    state: SessionState,
    *,
    error_type: str,
    wrong: str,
    correct: str,
    severity: str,
    explanation: str | None,
) -> Error:
    err = Error(
        session_id=state.session_id,
        user_id=state.user_id,
        error_type=error_type,
        wrong_text=wrong,
        correct_text=correct,
        severity=severity,
        explanation=explanation,
    )
    db.add(err)
    await db.commit()
    await db.refresh(err)
    return err


async def upsert_vocabulary(db: AsyncSession, user_id: int, word: str) -> tuple[Vocabulary, bool]:
    """So'zni qo'shadi yoki times_used ni oshiradi. (obj, is_new) qaytaradi."""
    existing = (
        await db.execute(select(Vocabulary).where(Vocabulary.user_id == user_id, Vocabulary.word == word))
    ).scalar_one_or_none()
    if existing is not None:
        existing.times_used += 1
        await db.commit()
        return existing, False
    vocab = Vocabulary(user_id=user_id, word=word, first_seen_at=utcnow(), times_used=1)
    db.add(vocab)
    await db.commit()
    return vocab, True


def build_summary(state: SessionState, scores: dict[str, int | None], duration: int) -> str:
    """Keyingi sessiya system prompt'i uchun qisqa, faktik xulosa."""
    parts = [
        f"{duration // 60} daq {duration % 60} son, daraja {state.level}",
        f"{state.sentences_spoken} gap / {state.words_spoken} so'z",
    ]
    if any(v is not None for v in scores.values()):
        parts.append("skorlar: " + ", ".join(f"{k[:4]}={v}" for k, v in scores.items() if v is not None))
    if state.errors_logged:
        top = state.errors_logged[-3:]
        parts.append("xatolar: " + "; ".join(f'"{e["wrong"]}"->"{e["correct"]}"' for e in top))
    if state.vocabulary:
        parts.append("yangi so'zlar: " + ", ".join(state.vocabulary[-8:]))
    if state.recent_lines:
        lines = " | ".join(f"{who}: {text}" for who, text in list(state.recent_lines)[-4:])
        parts.append(f"oxirgi gaplar: {lines}")
    return ". ".join(parts)[:1200]


def compute_streak(dates: list[date], today: date | None = None) -> int:
    """Ketma-ket faol kunlar soni (bugun yoki kechadan boshlab orqaga)."""
    today = today or utcnow().date()
    active = set(dates)
    start = today if today in active else today - timedelta(days=1)
    streak = 0
    while start in active:
        streak += 1
        start -= timedelta(days=1)
    return streak


async def finalize_session(db: AsyncSession, state: SessionState) -> dict[str, Any]:
    """Sessiyani yopadi: skorlar, statistika, progress va daraja DB ga yoziladi.

    Idempotent — ikkinchi chaqiruv hech narsa qilmaydi.
    """
    if state.finalized:
        return {}
    state.finalized = True
    state.flush_user_turn()

    ended = utcnow()
    duration = max(0, int((ended - state.started_at).total_seconds()))
    scores = state.final_scores()

    session = await db.get(Session, state.session_id)
    user = await db.get(User, state.user_id)
    if session is None or user is None:
        logger.error("finalize: sessiya yoki foydalanuvchi topilmadi (%s)", state.session_id)
        return {}

    session.ended_at = ended
    session.duration_seconds = duration
    session.sentences_spoken = state.sentences_spoken
    session.words_spoken = state.words_spoken
    session.fluency_score = scores["fluency"]
    session.grammar_score = scores["grammar"]
    session.pronunciation_score = scores["pronunciation"]
    session.comprehension_score = scores["comprehension"]
    session.summary = build_summary(state, scores, duration)

    # Daraja testi sessiyasida progress hisoblanmaydi (daraja set_level orqali belgilanadi)
    gain = 0.0 if state.placement else lvl.compute_gain(
        level=user.cefr_level,
        scores=scores,
        duration_seconds=duration,
        error_severities=state.error_severities,
        suggested_level=state.suggested_level,
    )
    result = lvl.apply_gain(user.cefr_level, user.level_progress, gain)
    user.cefr_level = result.level
    user.level_progress = result.progress
    user.last_active_at = ended

    today = ended.date()
    prog = (
        await db.execute(select(Progress).where(Progress.user_id == user.id, Progress.date == today))
    ).scalar_one_or_none()
    if prog is None:
        prog = Progress(user_id=user.id, date=today, sessions_count=0, total_sentences=0, total_words=0)
        db.add(prog)
    prog.sessions_count = (prog.sessions_count or 0) + 1
    prog.total_sentences = (prog.total_sentences or 0) + state.sentences_spoken
    prog.total_words = (prog.total_words or 0) + state.words_spoken
    prog.cefr_level = result.level

    await db.commit()
    logger.info(
        "Sessiya yakunlandi %s: %ss, %s gap, gain=%.1f, level=%s %s%%",
        state.session_id, duration, state.sentences_spoken, gain, result.level, result.progress,
    )
    return {
        "type": "session_end",
        "session_id": str(state.session_id),
        "duration_seconds": duration,
        "sentences_spoken": state.sentences_spoken,
        "words_spoken": state.words_spoken,
        "scores": scores,
        "errors_count": len(state.errors_logged),
        "new_words": state.vocabulary,
        "level": state.level_event(result, final=True),
    }
