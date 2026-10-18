"""To'lov chekini Gemini (vision) bilan tahlil qilish va qaror qabul qilish.

Qaror turlari:
  approve     — hamma shartlar bajarildi, tarif avtomatik yoqiladi
  review      — shubhali: admin Telegram'da tasdiqlaydi yoki rad etadi
  reject      — aniq firibgarlik belgisi (masalan, avval ishlatilgan chek)
  not_receipt — rasm umuman to'lov cheki emas (foydalanuvchidan qayta so'raladi)
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Literal

from google.genai import types
from pydantic import BaseModel, Field

from app.config import settings
from app.gemini.text import generate, receipt_models

logger = logging.getLogger(__name__)


class ReceiptAnalysis(BaseModel):
    is_receipt: bool = Field(description="Rasm bank/to'lov ilovasidagi pul o'tkazmasi cheki yoki skrinshotimi")
    is_successful: bool = Field(description="O'tkazma muvaffaqiyatli bajarilganmi (Успешно / Muvaffaqiyatli / Success)")
    amount: float | None = Field(default=None, description="O'tkazilgan summa, so'mda, faqat raqam (komissiyasiz)")
    currency: str | None = None
    recipient_card_last4: str | None = Field(default=None, description="QABUL QILUVCHI kartaning oxirgi 4 raqami")
    recipient_name: str | None = None
    datetime_local: str | None = Field(default=None, description="Chekdagi sana-vaqt ISO formatda: YYYY-MM-DDTHH:MM")
    transaction_id: str | None = Field(default=None, description="Tranzaksiya / chek / operatsiya raqami")
    app_or_bank: str | None = None
    signs_of_editing: bool = Field(description="Tahrirlash, montaj, shrift nomuvofiqligi belgilari bormi")
    editing_notes: str | None = None
    confidence: float = Field(ge=0, le=1, description="Umumiy ishonch 0..1")
    summary_uz: str = Field(description="Admin uchun o'zbekcha qisqa xulosa")


PROMPT = """You are a strict payment-receipt auditor for an Uzbek service.
Analyse the attached image (a screenshot or photo of a money-transfer receipt from Uzbek apps such as
Click, Payme, Uzum, Paynet, Apelsin, bank apps, Humo/Uzcard transfers).

Current date/time in Tashkent: {now_local}. Do NOT treat dates as suspicious because of the year —
the date freshness is checked by our system; only extract the printed date.

Expected payment:
- amount: {amount} UZS
- recipient card ends with: {last4}
- recipient name (may be partially masked): {holder}

Extract fields exactly as printed. Rules:
- amount: the transferred sum in UZS as a number (e.g. "29 000,00 so'm" -> 29000). Exclude commission.
- recipient_card_last4: last 4 digits of the RECIPIENT card (not the sender). null if not visible.
- datetime_local: date/time printed on the receipt, ISO "YYYY-MM-DDTHH:MM". null if absent.
- transaction_id: any receipt/transaction/operation/check number. null if absent.
- is_successful: true only if the receipt clearly states success.
- signs_of_editing: true only for visual manipulation evidence: inconsistent fonts within the same field,
  misaligned or pasted digits, cloned areas, cropped status, or a generator-made fake. Never because of the date.
- If the image is not a payment receipt at all, set is_receipt=false.
Respond only with JSON matching the schema."""


@dataclass
class Decision:
    action: Literal["approve", "review", "reject", "not_receipt"]
    reasons: list[str] = field(default_factory=list)

    @property
    def reason_text(self) -> str:
        return "; ".join(self.reasons) if self.reasons else "barcha tekshiruvlar o'tdi"


async def analyze_receipt(image: bytes, mime_type: str, expected_amount: int) -> ReceiptAnalysis:
    prompt = PROMPT.format(
        now_local=datetime.now(settings.local_tz).strftime("%Y-%m-%d %H:%M"),
        amount=expected_amount,
        last4=settings.card_last4 or "unknown",
        holder=settings.PAYMENT_CARD_HOLDER or "unknown",
    )
    response = await generate(
        [types.Part.from_bytes(data=image, mime_type=mime_type), prompt],
        models=receipt_models(),
        api_key=settings.receipt_api_key,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=ReceiptAnalysis,
            temperature=0,
        ),
    )
    parsed = response.parsed
    if isinstance(parsed, ReceiptAnalysis):
        return parsed
    return ReceiptAnalysis.model_validate(json.loads(response.text or "{}"))


def parse_receipt_time(value: str | None) -> datetime | None:
    """Chekdagi mahalliy vaqtni UTC'ga o'tkazadi."""
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.strip().replace(" ", "T").replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=settings.local_tz)
    return dt.astimezone(timezone.utc)


def normalize_tx(value: str | None) -> str | None:
    if not value:
        return None
    cleaned = "".join(ch for ch in value if ch.isalnum()).upper()
    return cleaned or None


def decide(
    a: ReceiptAnalysis,
    *,
    expected_amount: int,
    now: datetime,
    duplicate_image: bool,
    duplicate_tx: bool,
) -> Decision:
    """Tahlil natijasidan qaror chiqaradi (sof funksiya — testlanadi)."""
    if not a.is_receipt:
        return Decision("not_receipt", ["rasm to'lov cheki emas"])
    if duplicate_image:
        return Decision("reject", ["bu chek rasmi avval yuborilgan"])
    if duplicate_tx:
        return Decision("reject", ["bu tranzaksiya raqami avval ishlatilgan"])

    reasons: list[str] = []
    if not a.is_successful:
        reasons.append("o'tkazma muvaffaqiyatli ekani ko'rinmayapti")
    if a.amount is None:
        reasons.append("summa aniqlanmadi")
    elif a.amount + 0.5 < expected_amount:
        reasons.append(f"summa kam: {a.amount:,.0f} < {expected_amount:,}")
    elif a.amount > expected_amount * 1.5:
        reasons.append(f"summa kutilganidan ancha ko'p: {a.amount:,.0f}")
    last4 = settings.card_last4
    got4 = "".join(ch for ch in (a.recipient_card_last4 or "") if ch.isdigit())[-4:]
    if not last4:
        reasons.append("karta raqami sozlanmagan (PAYMENT_CARD_NUMBER)")
    elif not got4:
        reasons.append("qabul qiluvchi karta raqami ko'rinmayapti")
    elif got4 != last4:
        reasons.append(f"karta mos emas: *{got4} (kutilgan *{last4})")
    paid_at = parse_receipt_time(a.datetime_local)
    if paid_at is None:
        reasons.append("chek sanasi aniqlanmadi")
    else:
        if paid_at > now + timedelta(hours=1):
            reasons.append("chek sanasi kelajakda")
        elif now - paid_at > timedelta(hours=settings.RECEIPT_MAX_AGE_HOURS):
            reasons.append(f"chek eski ({settings.RECEIPT_MAX_AGE_HOURS} soatdan ko'p)")
    if not normalize_tx(a.transaction_id):
        reasons.append("tranzaksiya raqami yo'q")
    if a.signs_of_editing:
        reasons.append("tahrirlash belgilari: " + (a.editing_notes or "bor"))
    if a.confidence < settings.RECEIPT_AUTO_MIN_CONFIDENCE:
        reasons.append(f"ishonch past ({a.confidence:.2f})")
    return Decision("review", reasons) if reasons else Decision("approve")
