"""Admin paneli (faqat ADMIN_IDS): statistika, foydalanuvchilar, tarif berish/olish, tekshiruvdagi to'lovlar."""
from __future__ import annotations

import logging
from html import escape

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import BaseFilter, Command, CommandObject
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message, TelegramObject
from sqlalchemy import select

from app.bot.common import webapp_keyboard
from app.config import settings
from app.database import SessionLocal
from app.models import Payment, User
from app.services import admin_stats, billing

logger = logging.getLogger(__name__)
router = Router(name="admin")

GRANT_DAYS = (7, 30, 90)
LIST_LIMIT = 15


class IsAdmin(BaseFilter):
    async def __call__(self, event: TelegramObject) -> bool:
        user = getattr(event, "from_user", None)
        return user is not None and user.id in settings.admin_ids


router.message.filter(F.chat.type == "private", IsAdmin())
router.callback_query.filter(IsAdmin())

HELP = (
    "🛠 <b>Admin panel</b>\n\n"
    "/stats — umumiy statistika\n"
    "/users — oxirgi faol foydalanuvchilar\n"
    "/subs — faol Pro/Max obunachilar\n"
    "/pending — tekshiruvdagi to'lovlar\n"
    "/user <code>&lt;id | @username | ism&gt;</code> — foydalanuvchi kartasi va tarif tugmalari\n"
    "/grant <code>&lt;id | @username&gt; &lt;pro|max|free&gt; [kun]</code> — tarif berish\n\n"
    "Masalan: <code>/grant @ali pro 30</code> yoki <code>/grant 123456789 max 7</code>"
)


# ------------------------------------------------------------------ klaviaturalar
def menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="📊 Statistika", callback_data="am:stats"),
                InlineKeyboardButton(text="👥 Foydalanuvchilar", callback_data="am:users"),
            ],
            [
                InlineKeyboardButton(text="💎 Obunachilar", callback_data="am:subs"),
                InlineKeyboardButton(text="🧾 Tekshiruvda", callback_data="am:pending"),
            ],
        ]
    )


def user_kb(tg_id: int) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=f"💎 Pro +{d} kun", callback_data=f"ag:pro:{d}:{tg_id}") for d in GRANT_DAYS],
        [InlineKeyboardButton(text=f"👑 Max +{d} kun", callback_data=f"ag:max:{d}:{tg_id}") for d in GRANT_DAYS],
        [
            InlineKeyboardButton(text="🆓 Free'ga o'tkazish", callback_data=f"ag:free:0:{tg_id}"),
            InlineKeyboardButton(text="🔄 Yangilash", callback_data=f"au:{tg_id}"),
        ],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def users_kb(users: list[User]) -> InlineKeyboardMarkup:
    rows = []
    for u in users:
        badge = {"pro": "💎", "max": "👑"}.get(billing.effective_plan(u).code, "🆓")
        name = (u.first_name or "?")[:20] + (f" @{u.username}" if u.username else "")
        rows.append([InlineKeyboardButton(text=f"{badge} {name}", callback_data=f"au:{u.telegram_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ------------------------------------------------------------------ yordamchilar
async def _stats_text() -> str:
    async with SessionLocal() as db:
        return admin_stats.format_stats(await admin_stats.collect_stats(db))


async def _card(tg_id: int) -> str | None:
    async with SessionLocal() as db:
        u = (await db.execute(select(User).where(User.telegram_id == tg_id))).scalar_one_or_none()
        return await admin_stats.user_card(db, u) if u else None


async def _recent_users() -> list[User]:
    async with SessionLocal() as db:
        rows = await db.execute(select(User).order_by(User.last_active_at.desc()).limit(LIST_LIMIT))
        return list(rows.scalars().all())


async def _subscribers() -> list[User]:
    now = billing.utcnow()
    async with SessionLocal() as db:
        rows = await db.execute(
            select(User)
            .where(User.plan.in_(billing.PAID_PLANS), User.plan_expires_at > now)
            .order_by(User.plan_expires_at.asc())
            .limit(50)
        )
        return list(rows.scalars().all())


async def _apply_plan(bot: Bot, admin_id: int, query: str, plan_code: str, days: int | None) -> str:
    """Tarifni o'zgartiradi, foydalanuvchiga xabar beradi va admin uchun natija matnini qaytaradi."""
    async with SessionLocal() as db:
        u = await admin_stats.find_user(db, query)
        if u is None:
            return "❗️ Foydalanuvchi topilmadi. U avval botga /start bosgan bo'lishi kerak."
        expires = admin_stats.set_plan(u, plan_code, days)
        await db.commit()
        tg_id, name = u.telegram_id, u.first_name
    logger.info("Admin %s: %s -> %s (%s kun)", admin_id, tg_id, plan_code, days)
    if expires is None:
        return f"🆓 {escape(name)} (<code>{tg_id}</code>) Free tarifiga o'tkazildi."
    plan = billing.PLANS[plan_code]
    until = f"{expires.astimezone(settings.local_tz):%d.%m.%Y %H:%M}"
    try:
        await bot.send_message(
            tg_id,
            f"🎁 Sizga <b>{plan.title}</b> tarifi yoqildi!\nAmal qiladi: <b>{until}</b> gacha.\n\n"
            "Adam bilan gaplashishni davom ettiring 👇",
            reply_markup=webapp_keyboard(),
        )
        notified = "xabar yuborildi"
    except TelegramAPIError as exc:
        logger.warning("Foydalanuvchiga tarif xabari yuborilmadi: %s", exc)
        notified = "xabar yuborib bo'lmadi (botni bloklagan bo'lishi mumkin)"
    return f"✅ {escape(name)} (<code>{tg_id}</code>): <b>{plan.title}</b> {until} gacha — {notified}."


async def _send_pending(message: Message) -> None:
    from app.bot.payments import _admin_kb, _analysis_summary
    from app.services.receipts import ReceiptAnalysis

    async with SessionLocal() as db:
        rows = (
            await db.execute(select(Payment, User).join(User, User.id == Payment.user_id).where(Payment.status == "review"))
        ).all()
    if not rows:
        await message.answer("🧾 Tekshiruvda to'lov yo'q.")
        return
    for p, u in rows[:20]:
        analysis = ReceiptAnalysis.model_validate_json(p.analysis) if p.analysis else None
        text = (
            f"🧾 #{p.id} {u.first_name} (@{u.username or '-'}, id {u.telegram_id})\n"
            f"Tarif: {billing.PLANS[p.plan].title} — {billing.format_price(p.amount)}\n"
            f"Sabab: {p.decision_reason or '-'}\n\n{_analysis_summary(analysis)}"
        )
        if p.file_id:
            await message.answer_photo(p.file_id, caption=text[:1024], reply_markup=_admin_kb(p.id), parse_mode=None)
        else:
            await message.answer(text[:4096], reply_markup=_admin_kb(p.id), parse_mode=None)


# ------------------------------------------------------------------ buyruqlar
@router.message(Command("admin"))
async def cmd_admin(message: Message) -> None:
    await message.answer(HELP, reply_markup=menu_kb())


@router.message(Command("stats"))
async def cmd_stats(message: Message) -> None:
    await message.answer(await _stats_text(), reply_markup=menu_kb())


@router.message(Command("users"))
async def cmd_users(message: Message) -> None:
    users = await _recent_users()
    if not users:
        await message.answer("Hali foydalanuvchi yo'q.")
        return
    await message.answer(f"👥 Oxirgi faol {len(users)} ta foydalanuvchi — tanlang:", reply_markup=users_kb(users))


@router.message(Command("subs"))
async def cmd_subs(message: Message) -> None:
    users = await _subscribers()
    if not users:
        await message.answer("💎 Hozircha faol obunachi yo'q.")
        return
    lines = [
        f"{admin_stats.user_line(u)} — {u.plan_expires_at.astimezone(settings.local_tz):%d.%m}"  # type: ignore[union-attr]
        for u in users
    ]
    await message.answer(f"💎 <b>Faol obunachilar ({len(users)})</b>\n\n" + "\n".join(lines))


@router.message(Command("pending"))
async def cmd_pending(message: Message) -> None:
    await _send_pending(message)


@router.message(Command("user"))
async def cmd_user(message: Message, command: CommandObject) -> None:
    query = (command.args or "").strip()
    if not query:
        await message.answer("Foydalanish: <code>/user 123456789</code> yoki <code>/user @username</code> yoki <code>/user Ali</code>")
        return
    async with SessionLocal() as db:
        u = await admin_stats.find_user(db, query)
        if u is not None:
            text, tg_id = await admin_stats.user_card(db, u), u.telegram_id
        else:
            found = await admin_stats.search_users(db, query)
    if u is not None:
        await message.answer(text, reply_markup=user_kb(tg_id))
    elif found:
        await message.answer(f"🔎 «{escape(query)}» bo'yicha topildi — tanlang:", reply_markup=users_kb(found))
    else:
        await message.answer("❗️ Foydalanuvchi topilmadi.")


@router.message(Command("grant"))
async def cmd_grant(message: Message, command: CommandObject, bot: Bot) -> None:
    parts = (command.args or "").split()
    days: int | None = None
    if len(parts) == 3 and parts[2].isdigit() and 0 < int(parts[2]) <= 3650:
        days = int(parts[2])
    elif len(parts) != 2:
        parts = []
    if not parts or parts[1].lower() not in billing.PLANS:
        await message.answer("Foydalanish: <code>/grant &lt;id | @username&gt; &lt;pro|max|free&gt; [kun]</code>")
        return
    assert message.from_user is not None
    result = await _apply_plan(bot, message.from_user.id, parts[0], parts[1].lower(), days)
    await message.answer(result)


# ------------------------------------------------------------------ tugmalar
@router.callback_query(F.data.startswith("am:"))
async def cb_menu(cb: CallbackQuery) -> None:
    action = (cb.data or "").split(":", 1)[1]
    await cb.answer()
    if cb.message is None or not isinstance(cb.message, Message):
        return
    if action == "stats":
        await cb.message.answer(await _stats_text(), reply_markup=menu_kb())
    elif action == "users":
        await cmd_users(cb.message)
    elif action == "subs":
        await cmd_subs(cb.message)
    elif action == "pending":
        await _send_pending(cb.message)


@router.callback_query(F.data.startswith("au:"))
async def cb_user(cb: CallbackQuery) -> None:
    raw = (cb.data or "").split(":", 1)[1]
    text = await _card(int(raw)) if raw.lstrip("-").isdigit() else None
    if text is None:
        await cb.answer("Foydalanuvchi topilmadi", show_alert=True)
        return
    await cb.answer()
    if isinstance(cb.message, Message):
        try:
            if cb.message.text and cb.message.text.startswith(("🆓", "💎", "👑")) and cb.message.reply_markup:
                await cb.message.edit_text(text, reply_markup=user_kb(int(raw)))
                return
        except TelegramAPIError:
            pass
        await cb.message.answer(text, reply_markup=user_kb(int(raw)))


@router.callback_query(F.data.startswith("ag:"))
async def cb_grant(cb: CallbackQuery, bot: Bot) -> None:
    try:
        _, plan_code, raw_days, raw_id = (cb.data or "").split(":")
        days = int(raw_days) or None
        tg_id = int(raw_id)
    except ValueError:
        await cb.answer()
        return
    if plan_code not in billing.PLANS:
        await cb.answer()
        return
    result = await _apply_plan(bot, cb.from_user.id, str(tg_id), plan_code, days)
    await cb.answer("Bajarildi" if result.startswith(("✅", "🆓")) else "Xato", show_alert=False)
    if isinstance(cb.message, Message):
        card = await _card(tg_id)
        try:
            if card:
                await cb.message.edit_text(card, reply_markup=user_kb(tg_id))
        except TelegramAPIError:
            pass
        await cb.message.answer(result)
