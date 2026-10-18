"""Bot modullari uchun umumiy yordamchilar: foydalanuvchi, klaviaturalar, tarif matnlari."""
from __future__ import annotations

from html import escape

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, User as TgUser, WebAppInfo
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import upsert_user
from app.config import settings
from app.models import User
from app.schemas import TelegramUser
from app.services import billing


async def ensure_user(db: AsyncSession, tg: TgUser) -> User:
    return await upsert_user(
        db,
        TelegramUser(
            id=tg.id,
            first_name=tg.first_name or "",
            last_name=tg.last_name,
            username=tg.username,
            language_code=tg.language_code,
        ),
    )


def webapp_button(text: str = "🎤 Adam bilan gapirish") -> InlineKeyboardButton | None:
    if not settings.WEBAPP_URL.startswith("https://"):
        return None
    return InlineKeyboardButton(text=text, web_app=WebAppInfo(url=settings.WEBAPP_URL))


def webapp_keyboard() -> InlineKeyboardMarkup | None:
    """WebApp tugmasi (WEBAPP_URL HTTPS bo'lsagina Telegram qabul qiladi)."""
    btn = webapp_button()
    return InlineKeyboardMarkup(inline_keyboard=[[btn]]) if btn else None


def _limit_line(plan: billing.Plan) -> str:
    if plan.unlimited:
        return "cheksiz gaplashish"
    assert plan.limit_seconds is not None
    return f"har {plan.window_hours} soatda {billing.format_duration_uz(plan.limit_seconds)}"


def plans_text(user: User) -> str:
    current = billing.effective_plan(user)
    p = billing.PLANS
    lines = [
        "<b>💎 Adam tariflari</b>\n",
        f"🆓 <b>Free</b> — bepul\n   • {_limit_line(p['free'])}\n",
        f"💎 <b>Pro</b> — {billing.format_price(p['pro'].price)} / {settings.PLAN_DAYS} kun\n"
        f"   • {_limit_line(p['pro'])}\n   • limit yangilanishi haqida xabar shart emas — vaqt yetarli\n",
        f"👑 <b>Max</b> — {billing.format_price(p['max'].price)} / {settings.PLAN_DAYS} kun\n"
        f"   • {_limit_line(p['max'])}\n"
        "   • Adam'ni <b>guruhlarga</b> qo'shish: @mention yoki reply qilinsa tarjima, xatoni tuzatish, tushuntirish\n"
        "   • Adam'ni <b>kanalga</b> qo'shish: har kuni avtomatik ingliz tili darsi\n",
        f"Hozirgi tarifingiz: <b>{escape(current.title)}</b>",
    ]
    if current.code != "free" and user.plan_expires_at:
        exp = billing._utc(user.plan_expires_at)
        assert exp is not None
        lines[-1] += f" (tugash sanasi: {exp.astimezone(settings.local_tz):%d.%m.%Y %H:%M})"
    return "\n".join(lines)


def plans_keyboard() -> InlineKeyboardMarkup:
    p = billing.PLANS
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=f"💎 Pro — {billing.format_price(p['pro'].price)}", callback_data="buy:pro")],
            [InlineKeyboardButton(text=f"👑 Max — {billing.format_price(p['max'].price)}", callback_data="buy:max")],
        ]
    )


def status_text(user: User) -> str:
    q = billing.get_quota(user)
    lines = [f"<b>Tarifingiz:</b> {escape(q.plan.title)}"]
    if q.plan.code != "free" and user.plan_expires_at:
        exp = billing._utc(user.plan_expires_at)
        assert exp is not None
        lines.append(f"<b>Amal qiladi:</b> {exp.astimezone(settings.local_tz):%d.%m.%Y %H:%M} gacha")
    if q.remaining_seconds is None:
        lines.append("<b>Vaqt:</b> cheksiz ♾")
    else:
        lines.append(f"<b>Qolgan vaqt:</b> {billing.format_duration_uz(q.remaining_seconds)}")
        if q.resets_at:
            lines.append(f"<b>Limit yangilanadi:</b> {q.resets_at.astimezone(settings.local_tz):%d.%m %H:%M}")
    return "\n".join(lines)
