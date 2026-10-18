"""Progress API: foydalanuvchi faqat o'z ma'lumotlarini ko'radi (initData auth majburiy)."""
from __future__ import annotations

from collections import Counter
from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import CurrentUser
from app.config import settings
from app.database import get_db
from app.lessons.catalog import CATEGORIES
from app.models import Error, Progress, Session, User, Vocabulary, utcnow
from app.schemas import (
    DailyProgress,
    ErrorOut,
    ErrorsResponse,
    LevelInfo,
    MeResponse,
    PlanCatalogItem,
    PlanInfo,
    PlansResponse,
    ProgressResponse,
    SessionOut,
    SettingsIn,
    UserOut,
    VocabularyOut,
)
from app.services import billing
from app.services import level as lvl
from app.services.session_service import compute_streak

router = APIRouter(prefix="/api", tags=["progress"])
Db = Annotated[AsyncSession, Depends(get_db)]


def _level_info(user: User) -> LevelInfo:
    level = lvl.normalize_level(user.cefr_level)
    return LevelInfo(level=level, next_level=lvl.next_level(level), progress=max(0, min(100, user.level_progress)))


async def _streak(db: AsyncSession, user_id: int) -> int:
    since = utcnow().date() - timedelta(days=400)
    dates = (
        await db.execute(
            select(Progress.date).where(Progress.user_id == user_id, Progress.date >= since, Progress.sessions_count > 0)
        )
    ).scalars().all()
    return compute_streak(list(dates))


@router.get("/me", response_model=MeResponse)
async def me(user: CurrentUser, db: Db) -> MeResponse:
    """Home sahifasi uchun: daraja, streak, bugungi statistika, oxirgi sessiya."""
    today_row = (
        await db.execute(select(Progress).where(Progress.user_id == user.id, Progress.date == utcnow().date()))
    ).scalar_one_or_none()
    last = (
        await db.execute(
            select(Session)
            .where(Session.user_id == user.id, Session.ended_at.is_not(None))
            .order_by(Session.ended_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    return MeResponse(
        user=UserOut.model_validate(user),
        level=_level_info(user),
        streak_days=await _streak(db, user.id),
        today=DailyProgress.model_validate(today_row, from_attributes=True) if today_row else None,
        last_session=SessionOut.model_validate(last) if last else None,
        plan=PlanInfo.model_validate(billing.quota_dict(user)),
    )


@router.get("/plans", response_model=PlansResponse)
async def plans(user: CurrentUser) -> PlansResponse:
    """Tariflar katalogi va joriy holat (to'lov bot chatida amalga oshiriladi)."""
    from app.bot.bot import get_bot_username

    return PlansResponse(
        plans=[
            PlanCatalogItem(
                code=p.code,
                title=p.title,
                price=p.price,
                limit_seconds=p.limit_seconds,
                window_hours=p.window_hours,
                groups=p.groups,
            )
            for p in billing.PLANS.values()
        ],
        plan_days=settings.PLAN_DAYS,
        bot_username=await get_bot_username(),
        current=PlanInfo.model_validate(billing.quota_dict(user)),
    )


_LEVEL_ORDER = {"A1": 0, "A2": 1, "B1": 2, "B2": 3, "C1": 4, "C2": 5}


@router.get("/lessons")
async def lessons(user: CurrentUser) -> dict:
    """Vaziyatli darslar katalogi. `recommended` — foydalanuvchi darajasiga mos (±1) darslar."""
    user_rank = _LEVEL_ORDER.get(lvl.normalize_level(user.cefr_level), 0)
    return {
        "level": lvl.normalize_level(user.cefr_level),
        "categories": [
            {
                "id": c.id,
                "emoji": c.emoji,
                "title": c.title,
                "description": c.description,
                "topics": [
                    {
                        "id": t.id,
                        "emoji": t.emoji,
                        "title": t.title,
                        "level": t.level,
                        "situation": t.situation,
                        "task": t.task,
                        "phrases": list(t.phrases),
                        "grammar": t.grammar,
                        "recommended": abs(_LEVEL_ORDER.get(t.level, 0) - user_rank) <= 1,
                    }
                    for t in c.topics
                ],
            }
            for c in CATEGORIES
        ],
    }


@router.put("/settings", response_model=UserOut)
async def update_settings(body: SettingsIn, user: CurrentUser, db: Db) -> User:
    """Adam sozlamalarini yangilaydi. Daraja qo'lda o'zgartirilsa progress 0 dan boshlanadi."""
    data = body.model_dump(exclude_none=True)
    level = data.pop("cefr_level", None)
    if level is not None and level != user.cefr_level:
        user.cefr_level = level
        user.level_progress = 0
    if level is not None:
        user.needs_placement = False
    for key, value in data.items():
        setattr(user, key, value)
    await db.commit()
    await db.refresh(user)
    return user


@router.get("/progress", response_model=ProgressResponse)
async def progress(user: CurrentUser, db: Db, days: int = Query(default=7, ge=1, le=90)) -> ProgressResponse:
    """Oxirgi `days` kunlik grafik (bo'sh kunlar 0 bilan to'ldiriladi) + umumiy statistika."""
    today = utcnow().date()
    start = today - timedelta(days=days - 1)
    rows = (
        await db.execute(
            select(Progress).where(Progress.user_id == user.id, Progress.date >= start).order_by(Progress.date)
        )
    ).scalars().all()
    by_date = {r.date: r for r in rows}
    level_now = lvl.normalize_level(user.cefr_level)
    series = []
    for i in range(days):
        d = start + timedelta(days=i)
        r = by_date.get(d)
        series.append(
            DailyProgress(
                date=d,
                sessions_count=r.sessions_count if r else 0,
                total_sentences=r.total_sentences if r else 0,
                total_words=r.total_words if r else 0,
                cefr_level=r.cefr_level if r else level_now,
            )
        )

    totals_row = (
        await db.execute(
            select(
                func.count(Session.id),
                func.coalesce(func.sum(Session.duration_seconds), 0),
                func.coalesce(func.sum(Session.sentences_spoken), 0),
                func.coalesce(func.sum(Session.words_spoken), 0),
                func.avg(Session.fluency_score),
                func.avg(Session.grammar_score),
                func.avg(Session.pronunciation_score),
                func.avg(Session.comprehension_score),
            ).where(Session.user_id == user.id, Session.ended_at.is_not(None))
        )
    ).one()
    vocab_count = (await db.execute(select(func.count(Vocabulary.id)).where(Vocabulary.user_id == user.id))).scalar_one()
    errors_count = (await db.execute(select(func.count(Error.id)).where(Error.user_id == user.id))).scalar_one()

    def _avg(v: object) -> float | None:
        return round(float(v), 2) if v is not None else None

    return ProgressResponse(
        level=_level_info(user),
        streak_days=await _streak(db, user.id),
        days=series,
        totals={
            "sessions": int(totals_row[0]),
            "minutes": int(totals_row[1]) // 60,
            "sentences": int(totals_row[2]),
            "words": int(totals_row[3]),
            "vocabulary": int(vocab_count),
            "errors": int(errors_count),
        },
        average_scores={
            "fluency": _avg(totals_row[4]),
            "grammar": _avg(totals_row[5]),
            "pronunciation": _avg(totals_row[6]),
            "comprehension": _avg(totals_row[7]),
        },
    )


@router.get("/sessions", response_model=list[SessionOut])
async def sessions(user: CurrentUser, db: Db, limit: int = Query(default=20, ge=1, le=100)) -> list[Session]:
    rows = (
        await db.execute(
            select(Session)
            .where(Session.user_id == user.id, Session.ended_at.is_not(None))
            .order_by(Session.started_at.desc())
            .limit(limit)
        )
    ).scalars().all()
    return list(rows)


@router.get("/errors", response_model=ErrorsResponse)
async def errors(user: CurrentUser, db: Db, limit: int = Query(default=50, ge=1, le=200)) -> ErrorsResponse:
    """Oxirgi xatolar + tur va jiddiylik bo'yicha taqsimot (barcha xatolar bo'yicha)."""
    rows = (
        await db.execute(
            select(Error).where(Error.user_id == user.id).order_by(Error.created_at.desc(), Error.id.desc()).limit(limit)
        )
    ).scalars().all()
    by_type = dict(
        (await db.execute(select(Error.error_type, func.count()).where(Error.user_id == user.id).group_by(Error.error_type))).all()
    )
    by_sev = dict(
        (await db.execute(select(Error.severity, func.count()).where(Error.user_id == user.id).group_by(Error.severity))).all()
    )
    return ErrorsResponse(
        items=[ErrorOut.model_validate(r) for r in rows],
        by_type={k: int(v) for k, v in Counter(by_type).items()},
        by_severity={k: int(v) for k, v in Counter(by_sev).items()},
    )


@router.get("/vocabulary", response_model=list[VocabularyOut])
async def vocabulary(user: CurrentUser, db: Db, limit: int = Query(default=200, ge=1, le=1000)) -> list[Vocabulary]:
    rows = (
        await db.execute(
            select(Vocabulary)
            .where(Vocabulary.user_id == user.id)
            .order_by(Vocabulary.first_seen_at.desc())
            .limit(limit)
        )
    ).scalars().all()
    return list(rows)
