"""Tariflar, vaqt limiti va chek qarorlari."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.config import settings
from app.models import User
from app.services import billing
from app.services.receipts import ReceiptAnalysis, decide, normalize_tx, parse_receipt_time

NOW = datetime(2026, 10, 18, 12, 0, tzinfo=timezone.utc)


def make_user(**kw) -> User:  # noqa: ANN003
    base = dict(telegram_id=1, first_name="Ali", plan="free", usage_seconds=0, limit_notify=False)
    base.update(kw)
    return User(**base)


# ---------------------------------------------------------------- limitlar
def test_free_quota_fresh_user_has_two_minutes() -> None:
    q = billing.get_quota(make_user(), NOW)
    assert q.plan.code == "free"
    assert q.remaining_seconds == 120
    assert not q.exhausted


def test_free_usage_exhausts_and_flags_notify() -> None:
    u = make_user()
    billing.start_usage(u, NOW)
    q = billing.add_usage(u, 125, NOW + timedelta(seconds=125))
    assert q.exhausted
    assert u.limit_notify is True
    assert q.resets_at == NOW + timedelta(hours=12)


def test_free_window_resets_after_12_hours() -> None:
    u = make_user(usage_window_start=NOW, usage_seconds=120)
    assert billing.get_quota(u, NOW + timedelta(hours=11, minutes=59)).exhausted
    q = billing.get_quota(u, NOW + timedelta(hours=12, seconds=1))
    assert q.remaining_seconds == 120 and q.used_seconds == 0


def test_mark_limit_hit_removes_rounding_leftover() -> None:
    u = make_user(usage_window_start=NOW, usage_seconds=118)
    billing.mark_limit_hit(u, NOW)
    assert billing.get_quota(u, NOW).exhausted


def test_pro_has_one_hour_per_6h_and_no_notify() -> None:
    u = make_user(plan="pro", plan_expires_at=NOW + timedelta(days=10))
    billing.start_usage(u, NOW)
    q = billing.add_usage(u, 3600, NOW)
    assert q.plan.code == "pro" and q.exhausted
    assert u.limit_notify is False
    assert billing.get_quota(u, NOW + timedelta(hours=6, seconds=1)).remaining_seconds == 3600


def test_max_is_unlimited() -> None:
    u = make_user(plan="max", plan_expires_at=NOW + timedelta(days=1))
    billing.add_usage(u, 100000, NOW)
    q = billing.get_quota(u, NOW)
    assert q.remaining_seconds is None and not q.exhausted


def test_expired_paid_plan_falls_back_to_free() -> None:
    u = make_user(plan="max", plan_expires_at=NOW - timedelta(seconds=1))
    assert billing.effective_plan(u, NOW).code == "free"


def test_activate_plan_extends_same_plan_and_resets_usage() -> None:
    u = make_user(usage_window_start=NOW, usage_seconds=120, limit_notify=True)
    exp1 = billing.activate_plan(u, "pro", NOW)
    assert exp1 == NOW + timedelta(days=settings.PLAN_DAYS)
    assert u.usage_seconds == 0 and u.limit_notify is False
    exp2 = billing.activate_plan(u, "pro", NOW + timedelta(days=1))
    assert exp2 == exp1 + timedelta(days=settings.PLAN_DAYS)
    exp3 = billing.activate_plan(u, "max", NOW + timedelta(days=2))
    assert exp3 == NOW + timedelta(days=2 + settings.PLAN_DAYS)


def test_format_helpers() -> None:
    assert billing.format_price(29000) == "29 000 so'm"
    assert billing.format_duration_uz(120) == "2 daqiqa"
    assert billing.format_duration_uz(3600) == "1 soat"


# ---------------------------------------------------------------- chek qarori
@pytest.fixture
def card(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "PAYMENT_CARD_NUMBER", "8600 1234 5678 4321")


def good(**kw) -> ReceiptAnalysis:  # noqa: ANN003
    local = (NOW - timedelta(hours=1)).astimezone(settings.local_tz)
    data = dict(
        is_receipt=True,
        is_successful=True,
        amount=29000,
        currency="UZS",
        recipient_card_last4="4321",
        datetime_local=local.strftime("%Y-%m-%dT%H:%M"),
        transaction_id="TX-123 456",
        signs_of_editing=False,
        confidence=0.95,
        summary_uz="ok",
    )
    data.update(kw)
    return ReceiptAnalysis(**data)


def _decide(a: ReceiptAnalysis, **kw):  # noqa: ANN003, ANN202
    args = dict(expected_amount=29000, now=NOW, duplicate_image=False, duplicate_tx=False)
    args.update(kw)
    return decide(a, **args)


def test_receipt_auto_approve(card: None) -> None:
    d = _decide(good())
    assert d.action == "approve", d.reasons


@pytest.mark.parametrize(
    "override, fragment",
    [
        ({"amount": 20000}, "summa kam"),
        ({"recipient_card_last4": "9999"}, "karta mos emas"),
        ({"recipient_card_last4": None}, "karta raqami"),
        ({"is_successful": False}, "muvaffaqiyatli"),
        ({"signs_of_editing": True}, "tahrirlash"),
        ({"confidence": 0.5}, "ishonch past"),
        ({"transaction_id": None}, "tranzaksiya"),
        ({"datetime_local": "2026-10-10T10:00"}, "eski"),
    ],
)
def test_receipt_suspicious_goes_to_review(card: None, override: dict, fragment: str) -> None:
    d = _decide(good(**override))
    assert d.action == "review"
    assert fragment in d.reason_text


def test_receipt_duplicates_rejected(card: None) -> None:
    assert _decide(good(), duplicate_image=True).action == "reject"
    assert _decide(good(), duplicate_tx=True).action == "reject"


def test_not_a_receipt(card: None) -> None:
    assert _decide(good(is_receipt=False)).action == "not_receipt"


def test_receipt_without_configured_card_needs_review(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "PAYMENT_CARD_NUMBER", "")
    assert _decide(good()).action == "review"


def test_receipt_time_and_tx_parsing() -> None:
    assert parse_receipt_time("2026-10-18T17:00") == datetime(2026, 10, 18, 12, 0, tzinfo=timezone.utc)
    assert parse_receipt_time("garbage") is None
    assert normalize_tx(" tx-123 456 ") == "TX123456"
