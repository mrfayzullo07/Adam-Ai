"""Tariflar va to'lov: karta orqali o'tkazma -> chek rasmi -> Gemini tahlili -> avto/admin tasdiq."""
from __future__ import annotations

import hashlib
import io
import logging
from datetime import timedelta
from html import escape

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import func, select

from app.bot.common import ensure_user, plans_keyboard, plans_text, status_text, webapp_keyboard
from app.config import settings
from app.database import SessionLocal
from app.gemini.text import GeminiTextError
from app.models import Payment, User
from app.services import billing
from app.services.receipts import Decision, ReceiptAnalysis, analyze_receipt, decide, normalize_tx

logger = logging.getLogger(__name__)
router = Router(name="payments")

MAX_RECEIPT_BYTES = 10 * 1024 * 1024
AWAITING_TTL = timedelta(hours=24)
IMAGE_MIMES = {"image/jpeg", "image/png", "image/webp", "image/heic", "image/heif"}


def _is_admin(user_id: int | None) -> bool:
    return user_id is not None and user_id in settings.admin_ids


def _card_block(plan: billing.Plan) -> str:
    holder = f"\n👤 Egasi: <b>{escape(settings.PAYMENT_CARD_HOLDER)}</b>" if settings.PAYMENT_CARD_HOLDER else ""
    return (
        f"<b>{plan.title} tarifi — {billing.format_price(plan.price)} / {settings.PLAN_DAYS} kun</b>\n\n"
        f"1️⃣ Quyidagi kartaga aynan <b>{billing.format_price(plan.price)}</b> o'tkazing:\n"
        f"💳 <code>{escape(settings.PAYMENT_CARD_NUMBER)}</code>{holder}\n\n"
        "2️⃣ To'lovdan so'ng chekning <b>skrinshotini shu chatga</b> yuboring.\n"
        "   Chekda summa, qabul qiluvchi karta, sana va tranzaksiya raqami ko'rinsin.\n\n"
        "🤖 Chekni Adam avtomatik tekshiradi va tarif darhol yoqiladi."
    )


def _cancel_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ Bekor qilish", callback_data="buy:cancel")]])


def _admin_kb(payment_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Tasdiqlash", callback_data=f"adm:ok:{payment_id}"),
                InlineKeyboardButton(text="❌ Rad etish", callback_data=f"adm:no:{payment_id}"),
            ]
        ]
    )


def _activated_text(plan: billing.Plan, expires) -> str:  # noqa: ANN001
    extra = (
        "\n\n👥 Endi Adam'ni guruhlaringizga va kanalingizga qo'shishingiz mumkin "
        "(guruh/kanal sozlamalari → a'zo qo'shish → @bot nomi)."
        if plan.groups
        else ""
    )
    return (
        f"🎉 <b>{plan.title} tarifi yoqildi!</b>\n"
        f"Amal qiladi: <b>{expires.astimezone(settings.local_tz):%d.%m.%Y %H:%M}</b> gacha."
        f"{extra}\n\nAdam bilan gaplashishni davom ettiring 👇"
    )


def _analysis_summary(a: ReceiptAnalysis | None) -> str:
    if a is None:
        return "Tahlil yo'q"
    amount = f"{a.amount:,.0f}".replace(",", " ") if a.amount is not None else "?"
    return (
        f"Summa: {amount} | Karta: *{a.recipient_card_last4 or '?'} | Sana: {a.datetime_local or '?'}\n"
        f"Tranzaksiya: {a.transaction_id or '?'} | Ilova: {a.app_or_bank or '?'}\n"
        f"Muvaffaqiyatli: {'ha' if a.is_successful else 'yo`q'} | Tahrir belgisi: {'BOR' if a.signs_of_editing else 'yo`q'} "
        f"| Ishonch: {a.confidence:.2f}\n{a.summary_uz}"
    )


async def notify_admins(bot: Bot, text: str, *, photo: str | None = None, kb: InlineKeyboardMarkup | None = None) -> int:
    """Barcha adminlarga yuboradi; nechta adminga yetgani qaytariladi."""
    sent = 0
    for admin_id in settings.admin_ids:
        try:
            if photo:
                await bot.send_photo(admin_id, photo, caption=text[:1024], reply_markup=kb, parse_mode=None)
            else:
                await bot.send_message(admin_id, text[:4096], reply_markup=kb, parse_mode=None)
            sent += 1
        except TelegramAPIError as exc:
            logger.warning("Adminga yuborilmadi (%s): %s", admin_id, exc)
    return sent


# ------------------------------------------------------------------ foydalanuvchi buyruqlari
@router.message(Command("tarif", "tariflar", "plans"), F.chat.type == "private")
async def cmd_plans(message: Message) -> None:
    if message.from_user is None:
        return
    async with SessionLocal() as db:
        user = await ensure_user(db, message.from_user)
    await message.answer(plans_text(user), reply_markup=plans_keyboard())


@router.message(Command("mening", "status"), F.chat.type == "private")
async def cmd_status(message: Message) -> None:
    if message.from_user is None:
        return
    async with SessionLocal() as db:
        user = await ensure_user(db, message.from_user)
    await message.answer(status_text(user), reply_markup=plans_keyboard())


@router.callback_query(F.data == "plans")
async def cb_plans(cb: CallbackQuery) -> None:
    async with SessionLocal() as db:
        user = await ensure_user(db, cb.from_user)
    await cb.answer()
    if cb.message is not None:
        await cb.message.answer(plans_text(user), reply_markup=plans_keyboard())


@router.callback_query(F.data.in_({"buy:pro", "buy:max"}))
async def cb_buy(cb: CallbackQuery) -> None:
    plan = billing.PLANS[(cb.data or "").split(":", 1)[1]]
    if not settings.PAYMENT_CARD_NUMBER:
        await cb.answer("To'lov hali sozlanmagan. Birozdan so'ng urinib ko'ring.", show_alert=True)
        return
    async with SessionLocal() as db:
        user = await ensure_user(db, cb.from_user)
        # Oldingi kutilayotgan to'lovlar bekor qilinadi — bitta faol so'rov bo'ladi
        olds = (
            await db.execute(select(Payment).where(Payment.user_id == user.id, Payment.status == "awaiting_receipt"))
        ).scalars().all()
        for old in olds:
            old.status = "cancelled"
        db.add(Payment(user_id=user.id, plan=plan.code, amount=plan.price, status="awaiting_receipt"))
        await db.commit()
    await cb.answer()
    if cb.message is not None:
        await cb.message.answer(_card_block(plan), reply_markup=_cancel_kb())


@router.callback_query(F.data == "buy:cancel")
async def cb_cancel(cb: CallbackQuery) -> None:
    async with SessionLocal() as db:
        user = await ensure_user(db, cb.from_user)
        rows = (
            await db.execute(select(Payment).where(Payment.user_id == user.id, Payment.status == "awaiting_receipt"))
        ).scalars().all()
        for row in rows:
            row.status = "cancelled"
        await db.commit()
    await cb.answer("Bekor qilindi")
    if cb.message is not None:
        await cb.message.answer("To'lov bekor qilindi. Tariflar: /tarif")


# ------------------------------------------------------------------ chek qabul qilish
@router.message(F.chat.type == "private", F.photo | F.document)
async def on_receipt(message: Message, bot: Bot) -> None:
    if message.from_user is None:
        return
    if message.photo:
        file = message.photo[-1]
        mime = "image/jpeg"
        file_size = file.file_size or 0
    else:
        doc = message.document
        assert doc is not None
        if (doc.mime_type or "") not in IMAGE_MIMES:
            await message.answer("Chekni rasm (skrinshot) ko'rinishida yuboring 🖼")
            return
        file = doc
        mime = doc.mime_type or "image/jpeg"
        file_size = doc.file_size or 0
    if file_size > MAX_RECEIPT_BYTES:
        await message.answer("Rasm juda katta (10 MB dan oshmasin).")
        return

    async with SessionLocal() as db:
        user = await ensure_user(db, message.from_user)
        payment = (
            await db.execute(
                select(Payment)
                .where(
                    Payment.user_id == user.id,
                    Payment.status == "awaiting_receipt",
                    Payment.created_at >= billing.utcnow() - AWAITING_TTL,
                )
                .order_by(Payment.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if payment is None:
            busy = (
                await db.execute(
                    select(func.count()).select_from(Payment).where(
                        Payment.user_id == user.id, Payment.status.in_(("checking", "review"))
                    )
                )
            ).scalar_one()
            if busy:
                await message.answer("⏳ Chekingiz allaqachon tekshirilmoqda. Natija haqida xabar beraman.")
            else:
                await message.answer("Avval tarifni tanlang, keyin chekni yuboring 👇", reply_markup=plans_keyboard())
            return
        payment.status = "checking"
        payment.file_id = file.file_id
        await db.commit()
        payment_id = payment.id
        plan = billing.PLANS[payment.plan]
        expected = payment.amount

    wait_msg = await message.answer("🔎 Chek tekshirilmoqda, bir necha soniya kuting…")

    buf = io.BytesIO()
    try:
        await bot.download(file.file_id, destination=buf)
    except Exception:  # noqa: BLE001 — tarmoq xatolari ham to'lovni "checking"da qoldirmasin
        logger.exception("Chekni yuklab bo'lmadi")
        async with SessionLocal() as db:
            p = await db.get(Payment, payment_id)
            if p is not None:
                p.status = "awaiting_receipt"
                await db.commit()
        await wait_msg.edit_text("Rasmni yuklab bo'lmadi. Iltimos, qayta yuboring.")
        return
    image = buf.getvalue()
    image_hash = hashlib.sha256(image).hexdigest()

    analysis: ReceiptAnalysis | None = None
    try:
        analysis = await analyze_receipt(image, mime, expected)
    except (GeminiTextError, ValueError) as exc:
        logger.error("Chek tahlili xato: %s", exc)
    except Exception:  # noqa: BLE001 — kutilmagan xatoda ham chek admin tekshiruviga tushadi
        logger.exception("Chek tahlilida kutilmagan xato")

    async with SessionLocal() as db:
        p = await db.get(Payment, payment_id)
        u = await db.get(User, p.user_id) if p is not None else None
        if p is None or u is None:
            return
        tx = normalize_tx(analysis.transaction_id) if analysis else None
        dup_image = bool(
            (
                await db.execute(
                    select(func.count()).select_from(Payment).where(
                        Payment.image_hash == image_hash,
                        Payment.id != p.id,
                        Payment.status.in_(("approved", "review", "checking")),
                    )
                )
            ).scalar_one()
        )
        dup_tx = bool(
            tx
            and (
                await db.execute(
                    select(func.count()).select_from(Payment).where(
                        Payment.transaction_id == tx, Payment.id != p.id, Payment.status.in_(("approved", "review"))
                    )
                )
            ).scalar_one()
        )
        if analysis is None:
            decision = Decision("review", ["Gemini chekni tahlil qila olmadi"])
        else:
            decision = decide(
                analysis, expected_amount=expected, now=billing.utcnow(), duplicate_image=dup_image, duplicate_tx=dup_tx
            )

        p.analysis = analysis.model_dump_json() if analysis else None
        p.decision_reason = decision.reason_text
        if decision.action == "not_receipt":
            p.status = "awaiting_receipt"
            p.file_id = None
            await db.commit()
            await wait_msg.edit_text(
                "🤔 Bu rasm to'lov chekiga o'xshamaydi.\n"
                "Bank/Click/Payme ilovasidagi o'tkazma chekining skrinshotini yuboring."
            )
            return

        p.image_hash = image_hash
        p.transaction_id = tx
        if decision.action == "approve":
            expires = billing.activate_plan(u, plan.code)
            p.status = "approved"
            p.decided_by = "gemini"
            p.decided_at = billing.utcnow()
            await db.commit()
            await wait_msg.edit_text(_activated_text(plan, expires), reply_markup=webapp_keyboard())
            await notify_admins(
                bot,
                f"✅ AVTO-TASDIQ #{p.id}: {u.first_name} (@{u.username or '-'}, id {u.telegram_id}) — "
                f"{plan.title} {billing.format_price(expected)}\n{_analysis_summary(analysis)}",
                photo=p.file_id,
            )
            return

        if decision.action == "reject":
            p.status = "rejected"
            p.decided_by = "gemini"
            p.decided_at = billing.utcnow()
            await db.commit()
            await wait_msg.edit_text(
                f"❌ Chek qabul qilinmadi: {escape(decision.reason_text)}.\n"
                "Xatolik bo'lsa, yangi to'lov chekini yuboring yoki admin bilan bog'laning."
            )
            await notify_admins(
                bot,
                f"⛔ AVTO-RAD #{p.id}: {u.first_name} (id {u.telegram_id}) — {decision.reason_text}\n"
                f"{_analysis_summary(analysis)}",
                photo=p.file_id,
            )
            return

        # review
        p.status = "review"
        await db.commit()
        sent = await notify_admins(
            bot,
            f"🧾 TEKSHIRISH KERAK #{p.id}\n{u.first_name} (@{u.username or '-'}, id {u.telegram_id})\n"
            f"Tarif: {plan.title} — {billing.format_price(expected)}\n"
            f"Sabab: {decision.reason_text}\n\n{_analysis_summary(analysis)}",
            photo=p.file_id,
            kb=_admin_kb(p.id),
        )
        if not sent:
            logger.warning("To'lov #%s ko'rib chiqish uchun admin yo'q (ADMIN_IDS bo'sh?)", p.id)
    await wait_msg.edit_text(
        "🧾 Chekingiz qabul qilindi va admin tekshiruviga yuborildi.\n"
        "Odatda bu tez bo'ladi — tasdiqlangach darhol xabar beraman."
    )


# ------------------------------------------------------------------ admin
@router.callback_query(F.data.startswith("adm:"))
async def cb_admin(cb: CallbackQuery, bot: Bot) -> None:
    if not _is_admin(cb.from_user.id):
        await cb.answer("Ruxsat yo'q", show_alert=True)
        return
    try:
        _, action, raw_id = (cb.data or "").split(":")
        payment_id = int(raw_id)
    except ValueError:
        await cb.answer()
        return
    async with SessionLocal() as db:
        p = await db.get(Payment, payment_id)
        if p is None:
            await cb.answer("To'lov topilmadi", show_alert=True)
            return
        if p.status != "review":
            await cb.answer(f"Allaqachon hal qilingan: {p.status}", show_alert=True)
            return
        u = await db.get(User, p.user_id)
        if u is None:
            await cb.answer("Foydalanuvchi topilmadi", show_alert=True)
            return
        plan = billing.PLANS[p.plan]
        p.decided_by = f"admin:{cb.from_user.id}"
        p.decided_at = billing.utcnow()
        if action == "ok":
            expires = billing.activate_plan(u, plan.code)
            p.status = "approved"
            await db.commit()
            user_text = _activated_text(plan, expires)
            verdict = "✅ TASDIQLANDI"
            kb = webapp_keyboard()
        else:
            p.status = "rejected"
            await db.commit()
            user_text = (
                "❌ To'lov cheki admin tomonidan rad etildi.\n"
                "Xato bo'lsa, to'g'ri chekni qayta yuboring: /tarif"
            )
            verdict = "❌ RAD ETILDI"
            kb = None
        tg_id = u.telegram_id
    try:
        await bot.send_message(tg_id, user_text, reply_markup=kb)
    except TelegramAPIError as exc:
        logger.warning("Foydalanuvchiga natija yuborilmadi: %s", exc)
    await cb.answer(verdict)
    if cb.message is not None:
        try:
            base = cb.message.caption or cb.message.text or ""
            new = f"{base}\n\n{verdict} — {cb.from_user.first_name}"[:1024]
            if cb.message.photo:
                await cb.message.edit_caption(caption=new, reply_markup=None, parse_mode=None)
            else:
                await cb.message.edit_text(new, reply_markup=None, parse_mode=None)
        except TelegramAPIError:
            pass

