"""Telegram bot buyruqlari (shaxsiy chat): /start va /help."""
from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.bot.common import ensure_user, plans_keyboard, plans_text, status_text, webapp_button, webapp_keyboard
from app.config import settings
from app.database import SessionLocal

logger = logging.getLogger(__name__)
router = Router(name="adam")

WELCOME_TEXT = (
    "Assalomu alaykum, <b>{name}</b>! 👋\n\n"
    "Men <b>Adam</b> — sizning shaxsiy ingliz tili repetitoringizman.\n\n"
    "🎤 Men bilan <b>ovoz orqali</b> gaplashasiz: men o'zbekcha tushuntiraman, "
    "inglizcha mashq qildiraman va xatolaringizni real vaqtda ko'rsataman.\n"
    "📈 Darajangiz (A1–C2) har sessiyadan keyin yangilanib boradi.\n\n"
    "Boshlash uchun pastdagi tugmani bosing 👇"
)

HELP_TEXT = (
    "<b>Adam'dan qanday foydalaniladi?</b>\n\n"
    "1️⃣ «🎤 Adam bilan gapirish» tugmasini bosing.\n"
    "2️⃣ Mikrofonga ruxsat bering.\n"
    "3️⃣ Rejimni tanlang:\n"
    "   • <b>Erkin suhbat</b> — bir marta bosing va bemalol gapiring;\n"
    "   • <b>Bosib gapirish</b> — tugmani bosib turib gapiring.\n"
    "4️⃣ Adam javob beradi, xatolar ekranda chiqadi.\n\n"
    "💡 Maslahat: tinch joyda, telefonni yaqin tutib gapiring.\n"
    "⏱ Bitta sessiya {minutes} daqiqagacha davom etadi.\n\n"
    "/start — bosh menyu\n/tarif — tariflar va to'lov\n/mening — tarifim va qolgan vaqt\n/help — yordam"
)


def start_keyboard() -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    btn = webapp_button()
    if btn is not None:
        rows.append([btn])
    rows.append([InlineKeyboardButton(text="💎 Tariflar", callback_data="plans")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.message(CommandStart(), F.chat.type == "private")
async def cmd_start(message: Message, command: CommandObject) -> None:
    """Foydalanuvchini DB ga yozadi va WebApp tugmasini yuboradi. /start plans — tariflar."""
    if message.from_user is None:
        return
    async with SessionLocal() as db:
        user = await ensure_user(db, message.from_user)

    if (command.args or "").strip() == "plans":
        await message.answer(plans_text(user), reply_markup=plans_keyboard())
        return

    text = WELCOME_TEXT.format(name=(user.first_name or "do'stim")) + "\n\n" + status_text(user)
    if webapp_button() is None:
        text += "\n\n⚠️ WebApp manzili hali sozlanmagan (WEBAPP_URL https:// bo'lishi kerak)."
    await message.answer(text, reply_markup=start_keyboard())


@router.message(Command("help"), F.chat.type == "private")
async def cmd_help(message: Message) -> None:
    await message.answer(HELP_TEXT.format(minutes=settings.SESSION_TIMEOUT_SECONDS // 60), reply_markup=webapp_keyboard())


@router.message(F.text, F.chat.type == "private")
async def fallback(message: Message) -> None:
    """Boshqa matnlarga qisqa yo'naltirish."""
    await message.answer("Men bilan Mini App ichida ovoz orqali gaplashamiz 🎤", reply_markup=webapp_keyboard())
