"""5. Sessiya yakuni -> DB yozuvlari, daraja algoritmi, streak."""
from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import select

from app.database import SessionLocal
from app.models import Progress, Session, User, utcnow
from app.services import level as lvl
from app.services.session_service import compute_streak, english_word_count, finalize_session


async def test_finalize_writes_session_progress_and_level(user_and_session) -> None:
    user, session, state = user_and_session
    state.started_at = utcnow() - timedelta(minutes=10)
    state.add_user_transcript("My name is Vali. I like plov")
    state.flush_user_turn()
    state.add_user_transcript("I am from Tashkent")
    state.flush_user_turn()
    state.score_updates = [
        {"fluency": 4, "grammar": 4, "pronunciation": 4, "comprehension": 5},
        {"fluency": 5, "grammar": 4, "pronunciation": 4, "comprehension": 5},
    ]

    async with SessionLocal() as db:
        summary = await finalize_session(db, state)

    assert summary["type"] == "session_end"
    assert summary["sentences_spoken"] == 2
    assert summary["words_spoken"] == 11
    assert summary["level"]["final"] is True

    async with SessionLocal() as db:
        row = await db.get(Session, session.id)
        u = await db.get(User, user.id)
        prog = (await db.execute(select(Progress).where(Progress.user_id == user.id))).scalar_one()

    assert row.ended_at is not None and row.duration_seconds >= 599
    assert (row.fluency_score, row.grammar_score, row.pronunciation_score, row.comprehension_score) == (5, 4, 4, 5)
    assert row.summary and "Tashkent" in row.summary
    assert u.level_progress > 0 and u.cefr_level == "A1"
    assert prog.sessions_count == 1 and prog.total_sentences == 2 and prog.total_words == 11

    async with SessionLocal() as db:
        assert await finalize_session(db, state) == {}  # idempotent


async def test_short_session_gives_no_progress(user_and_session) -> None:
    user, _, state = user_and_session
    state.score_updates = [{"fluency": 5, "grammar": 5, "pronunciation": 5, "comprehension": 5}]
    async with SessionLocal() as db:
        await finalize_session(db, state)
        u = await db.get(User, user.id)
    assert u.level_progress == 0


def test_level_algorithm() -> None:
    perfect = {"fluency": 5, "grammar": 5, "pronunciation": 5, "comprehension": 5}
    weak = {"fluency": 1, "grammar": 1, "pronunciation": 1, "comprehension": 1}
    gain = lvl.compute_gain(level="A1", scores=perfect, duration_seconds=600, error_severities=[])
    assert gain == 25.0
    assert lvl.compute_gain(level="A1", scores=weak, duration_seconds=600, error_severities=["high"] * 10) == -10.0
    assert lvl.compute_gain(level="B2", scores=perfect, duration_seconds=600, error_severities=[]) < gain

    up = lvl.apply_gain("A1", 90, 25.0)
    assert up.leveled_up and up.level == "A2" and up.progress == 15
    assert lvl.apply_gain("A2", 5, -10).progress == 0
    assert lvl.apply_gain("C2", 100, 25).level == "C2"
    assert lvl.normalize_level("x") == "A1" and lvl.next_level("C2") is None


def test_streak_and_word_count() -> None:
    today = date(2026, 10, 17)
    assert compute_streak([today, today - timedelta(days=1), today - timedelta(days=2)], today) == 3
    assert compute_streak([today - timedelta(days=1)], today) == 1
    assert compute_streak([today - timedelta(days=3)], today) == 0
    assert english_word_count("Salom, men o'qiyman. I am a student") == 4
