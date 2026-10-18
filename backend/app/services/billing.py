"""Tariflar (Free / Pro / Max), vaqt limiti va tarifni yoqish.

Limit modeli: "oyna" foydalanuvchi birinchi gapira boshlaganda ochiladi va
plan.window_hours davom etadi. Oyna ichida plan.limit_seconds gacha gaplashish mumkin.
Oyna tugagach hisob nolga qaytadi (Free foydalanuvchiga xabar yuboriladi).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from app.config import settings
from app.models import User


@dataclass(frozen=True)
class Plan:
    code: str
    title: str
    price: int
    window_hours: int | None  # None = cheksiz
    limit_seconds: int | None  # None = cheksiz
    groups: bool  # guruh/kanalga qo'shish huquqi

    @property
    def unlimited(self) -> bool:
        return self.limit_seconds is None


PLANS: dict[str, Plan] = {
    "free": Plan("free", "Free", 0, 12, 2 * 60, False),
    "pro": Plan("pro", "Pro", settings.PRO_PRICE, 6, 60 * 60, False),
    "max": Plan("max", "Max", settings.MAX_PRICE, None, None, True),
}
PAID_PLANS = ("pro", "max")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def effective_plan(user: User, now: datetime | None = None) -> Plan:
    """Muddati tugagan pullik tarif Free hisoblanadi."""
    now = now or utcnow()
    code = user.plan if user.plan in PLANS else "free"
    if code != "free":
        exp = _utc(user.plan_expires_at)
        if exp is None or exp <= now:
            code = "free"
    return PLANS[code]


@dataclass(frozen=True)
class Quota:
    plan: Plan
    used_seconds: int
    remaining_seconds: int | None  # None = cheksiz
    resets_at: datetime | None  # oyna qachon yangilanadi (faqat ishlatilgan bo'lsa)

    @property
    def exhausted(self) -> bool:
        return self.remaining_seconds is not None and self.remaining_seconds <= 0


def _window_active(user: User, plan: Plan, now: datetime) -> bool:
    start = _utc(user.usage_window_start)
    return start is not None and plan.window_hours is not None and now < start + timedelta(hours=plan.window_hours)


def get_quota(user: User, now: datetime | None = None) -> Quota:
    now = now or utcnow()
    plan = effective_plan(user, now)
    if plan.unlimited:
        return Quota(plan, 0, None, None)
    assert plan.limit_seconds is not None and plan.window_hours is not None
    if not _window_active(user, plan, now):
        return Quota(plan, 0, plan.limit_seconds, None)
    used = max(0, user.usage_seconds or 0)
    start = _utc(user.usage_window_start)
    assert start is not None
    return Quota(plan, used, max(0, plan.limit_seconds - used), start + timedelta(hours=plan.window_hours))


def start_usage(user: User, now: datetime | None = None) -> None:
    """Sessiya boshida: oyna tugagan yoki yo'q bo'lsa yangisini ochadi."""
    now = now or utcnow()
    plan = effective_plan(user, now)
    if plan.unlimited:
        return
    if not _window_active(user, plan, now):
        user.usage_window_start = now
        user.usage_seconds = 0


def add_usage(user: User, seconds: int, now: datetime | None = None) -> Quota:
    """Sessiya oxirida sarflangan vaqtni yozadi; limit tugasa Free uchun xabar belgisi qo'yiladi."""
    now = now or utcnow()
    plan = effective_plan(user, now)
    if plan.unlimited or seconds <= 0:
        return get_quota(user, now)
    if not _window_active(user, plan, now):
        user.usage_window_start = now
        user.usage_seconds = 0
    user.usage_seconds = (user.usage_seconds or 0) + int(seconds)
    quota = get_quota(user, now)
    if quota.exhausted and plan.code == "free":
        user.limit_notify = True
    return quota


def mark_limit_hit(user: User, now: datetime | None = None) -> None:
    """Limit tugaganini qayd etadi (yaxlitlash qoldig'i qolmasin) va Free uchun xabar belgisini qo'yadi."""
    now = now or utcnow()
    plan = effective_plan(user, now)
    if plan.unlimited:
        return
    assert plan.limit_seconds is not None
    if not _window_active(user, plan, now):
        user.usage_window_start = now
    user.usage_seconds = max(user.usage_seconds or 0, plan.limit_seconds)
    if plan.code == "free":
        user.limit_notify = True


def activate_plan(user: User, plan_code: str, now: datetime | None = None, days: int | None = None) -> datetime:
    """Tarifni `days` (standart: PLAN_DAYS) kunga yoqadi. Shu tarif hali amalda bo'lsa muddat ustiga qo'shiladi."""
    now = now or utcnow()
    current = effective_plan(user, now)
    base = now
    if current.code == plan_code:
        base = _utc(user.plan_expires_at) or now
    expires = base + timedelta(days=days or settings.PLAN_DAYS)
    user.plan = plan_code
    user.plan_expires_at = expires
    user.plan_reminded = False
    user.usage_window_start = None
    user.usage_seconds = 0
    user.limit_notify = False
    return expires


def quota_dict(user: User, now: datetime | None = None) -> dict[str, object]:
    """API va WS uchun tarif/limit ma'lumoti."""
    q = get_quota(user, now)
    expires = _utc(user.plan_expires_at) if q.plan.code != "free" else None
    return {
        "plan": q.plan.code,
        "plan_title": q.plan.title,
        "plan_expires_at": expires.isoformat() if expires else None,
        "limit_seconds": q.plan.limit_seconds,
        "window_hours": q.plan.window_hours,
        "used_seconds": q.used_seconds,
        "remaining_seconds": q.remaining_seconds,
        "resets_at": q.resets_at.isoformat() if q.resets_at else None,
    }


def format_duration_uz(seconds: int) -> str:
    seconds = max(0, int(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h} soat {m} daqiqa" if m else f"{h} soat"
    if m:
        return f"{m} daqiqa {s} soniya" if s else f"{m} daqiqa"
    return f"{s} soniya"


def format_price(amount: int) -> str:
    return f"{amount:,}".replace(",", " ") + " so'm"
