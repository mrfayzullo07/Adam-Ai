"""Admin uchun: statistika yig'ish, foydalanuvchini topish va tarifni qo'lda boshqarish."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, time, timedelta, timezone
from html import escape

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import BotChat, Payment, Session, User
from app.services import billing


@dataclass
class Stats:
    users_total: int = 0
    users_onboarded: int = 0
    new_today: int = 0
    new_7d: int = 0
    active_today: int = 0
    active_7d: int = 0
    sessions_today: int = 0
    minutes_today: int = 0
    sessions_7d: int = 0
    minutes_7d: int = 0
    minutes_total: int = 0
    pro_active: int = 0
    max_active: int = 0
    expiring_3d: int = 0
    revenue_today: int = 0
    revenue_7d: int = 0
    revenue_30d: int = 0
    revenue_total: int = 0
    payments_approved: int = 0
    payments_review: int = 0
    payments_rejected_30d: int = 0
    groups_active: int = 0
    levels: dict[str, int] = field(default_factory=dict)


def local_day_start(now: datetime) -> datetime:
    """Toshkent vaqti bo'yicha bugungi kun boshi (UTC'da)."""
    local = now.astimezone(settings.local_tz)
    return datetime.combine(local.date(), time.min, tzinfo=settings.local_tz).astimezone(timezone.utc)


async def _scalar(db: AsyncSession, stmt) -> int:  # noqa: ANN001
    return int((await db.execute(stmt)).scalar_one() or 0)


async def collect_stats(db: AsyncSession, now: datetime | None = None) -> Stats:
    now = now or billing.utcnow()
    today = local_day_start(now)
    d7, d30 = now - timedelta(days=7), now - timedelta(days=30)
    count_users = select(func.count()).select_from(User)
    sessions = select(func.count()).select_from(Session)
    seconds = select(func.coalesce(func.sum(Session.duration_seconds), 0))
    revenue = select(func.coalesce(func.sum(Payment.amount), 0)).where(Payment.status == "approved")
    paid_active = select(func.count()).select_from(User).where(User.plan_expires_at > now)

    s = Stats()
    s.users_total = await _scalar(db, count_users)
    s.users_onboarded = await _scalar(db, count_users.where(User.onboarded.is_(True)))
    s.new_today = await _scalar(db, count_users.where(User.created_at >= today))
    s.new_7d = await _scalar(db, count_users.where(User.created_at >= d7))
    s.active_today = await _scalar(db, count_users.where(User.last_active_at >= today))
    s.active_7d = await _scalar(db, count_users.where(User.last_active_at >= d7))
    s.sessions_today = await _scalar(db, sessions.where(Session.started_at >= today))
    s.minutes_today = await _scalar(db, seconds.where(Session.started_at >= today)) // 60
    s.sessions_7d = await _scalar(db, sessions.where(Session.started_at >= d7))
    s.minutes_7d = await _scalar(db, seconds.where(Session.started_at >= d7)) // 60
    s.minutes_total = await _scalar(db, seconds) // 60
    s.pro_active = await _scalar(db, paid_active.where(User.plan == "pro"))
    s.max_active = await _scalar(db, paid_active.where(User.plan == "max"))
    s.expiring_3d = await _scalar(
        db, paid_active.where(User.plan != "free", User.plan_expires_at <= now + timedelta(days=3))
    )
    s.revenue_today = await _scalar(db, revenue.where(Payment.decided_at >= today))
    s.revenue_7d = await _scalar(db, revenue.where(Payment.decided_at >= d7))
    s.revenue_30d = await _scalar(db, revenue.where(Payment.decided_at >= d30))
    s.revenue_total = await _scalar(db, revenue)
    s.payments_approved = await _scalar(db, select(func.count()).select_from(Payment).where(Payment.status == "approved"))
    s.payments_review = await _scalar(db, select(func.count()).select_from(Payment).where(Payment.status == "review"))
    s.payments_rejected_30d = await _scalar(
        db, select(func.count()).select_from(Payment).where(Payment.status == "rejected", Payment.created_at >= d30)
    )
    s.groups_active = await _scalar(db, select(func.count()).select_from(BotChat).where(BotChat.active.is_(True)))
    rows = (await db.execute(select(User.cefr_level, func.count()).group_by(User.cefr_level))).all()
    s.levels = {lvl: int(n) for lvl, n in sorted(rows)}
    return s


def format_stats(s: Stats, now: datetime | None = None) -> str:
    now = now or billing.utcnow()
    p = billing.format_price
    levels = " · ".join(f"{k}: {v}" for k, v in s.levels.items()) or "—"
    return (
        f"📊 <b>Adam statistikasi</b> — {now.astimezone(settings.local_tz):%d.%m.%Y %H:%M}\n\n"
        f"👥 <b>Foydalanuvchilar:</b> {s.users_total} (ro'yxatdan to'liq o'tgan: {s.users_onboarded})\n"
        f"🆕 Yangi: bugun <b>{s.new_today}</b> · 7 kun {s.new_7d}\n"
        f"🔥 Faol: bugun <b>{s.active_today}</b> · 7 kun {s.active_7d}\n\n"
        f"🎤 <b>Sessiyalar:</b> bugun {s.sessions_today} ({s.minutes_today} daq) · "
        f"7 kun {s.sessions_7d} ({s.minutes_7d} daq)\n"
        f"⏱ Jami gaplashilgan: {s.minutes_total} daqiqa\n\n"
        f"💎 <b>Obunachilar:</b> Pro {s.pro_active} · Max {s.max_active}"
        f"{f' · ⚠️ 3 kunda tugaydi: {s.expiring_3d}' if s.expiring_3d else ''}\n"
        f"💰 <b>Daromad:</b> bugun {p(s.revenue_today)} · 7 kun {p(s.revenue_7d)} · 30 kun {p(s.revenue_30d)}\n"
        f"💵 Jami: <b>{p(s.revenue_total)}</b> ({s.payments_approved} ta to'lov)\n"
        f"🧾 Tekshiruvda: <b>{s.payments_review}</b> · 30 kunda rad etilgan: {s.payments_rejected_30d}\n\n"
        f"👨‍👩‍👧 Faol guruh/kanallar: {s.groups_active}\n"
        f"📈 Darajalar: {levels}"
    )


async def find_user(db: AsyncSession, query: str) -> User | None:
    """Telegram ID, @username yoki username bo'yicha qidiradi."""
    q = query.strip()
    if not q:
        return None
    if q.lstrip("-").isdigit():
        return (await db.execute(select(User).where(User.telegram_id == int(q)))).scalar_one_or_none()
    name = q.lstrip("@").lower()
    return (
        await db.execute(select(User).where(func.lower(User.username) == name).limit(1))
    ).scalar_one_or_none()


async def search_users(db: AsyncSession, query: str, limit: int = 10) -> list[User]:
    """Ism yoki username bo'yicha qisman qidiruv."""
    like = f"%{query.strip().lstrip('@').lower()}%"
    rows = await db.execute(
        select(User)
        .where(or_(func.lower(User.username).like(like), func.lower(User.first_name).like(like)))
        .order_by(User.last_active_at.desc())
        .limit(limit)
    )
    return list(rows.scalars().all())


def _fmt_dt(dt: datetime | None) -> str:
    if dt is None:
        return "—"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return f"{dt.astimezone(settings.local_tz):%d.%m.%Y %H:%M}"


def user_line(u: User, now: datetime | None = None) -> str:
    plan = billing.effective_plan(u, now)
    tag = f"@{escape(u.username)}" if u.username else "—"
    badge = {"pro": "💎", "max": "👑"}.get(plan.code, "🆓")
    return f"{badge} <b>{escape(u.first_name or '?')}</b> {tag} · <code>{u.telegram_id}</code> · {u.cefr_level}"


async def user_card(db: AsyncSession, u: User, now: datetime | None = None) -> str:
    now = now or billing.utcnow()
    plan = billing.effective_plan(u, now)
    q = billing.get_quota(u, now)
    n_sessions = await _scalar(db, select(func.count()).select_from(Session).where(Session.user_id == u.id))
    minutes = await _scalar(
        db, select(func.coalesce(func.sum(Session.duration_seconds), 0)).where(Session.user_id == u.id)
    ) // 60
    paid = await _scalar(
        db, select(func.coalesce(func.sum(Payment.amount), 0)).where(Payment.user_id == u.id, Payment.status == "approved")
    )
    remaining = "cheksiz" if q.remaining_seconds is None else billing.format_duration_uz(q.remaining_seconds)
    expires = f" — {_fmt_dt(u.plan_expires_at)} gacha" if plan.code != "free" else ""
    return (
        f"{user_line(u, now)}\n\n"
        f"Tarif: <b>{plan.title}</b>{expires}\n"
        f"Qolgan vaqt: {remaining}\n"
        f"Daraja: {u.cefr_level} ({u.level_progress}%)\n"
        f"Sessiyalar: {n_sessions} · {minutes} daqiqa\n"
        f"To'lagan: {billing.format_price(paid)}\n"
        f"Ro'yxatdan o'tgan: {_fmt_dt(u.created_at)}\n"
        f"Oxirgi faollik: {_fmt_dt(u.last_active_at)}"
    )


def set_plan(u: User, plan_code: str, days: int | None = None, now: datetime | None = None) -> datetime | None:
    """Admin tomonidan tarif berish. free — darhol bekor qiladi (None qaytaradi)."""
    if plan_code == "free":
        u.plan, u.plan_expires_at = "free", None
        u.usage_window_start, u.usage_seconds, u.limit_notify = None, 0, False
        return None
    return billing.activate_plan(u, plan_code, now, days=days)
