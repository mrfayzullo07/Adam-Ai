"""Admin: foydalanuvchini topish, tarif berish/olish va statistika."""
from __future__ import annotations

from datetime import timedelta

from app.database import SessionLocal
from app.models import Payment, Session, User
from app.services import admin_stats, billing


async def _seed() -> None:
    now = billing.utcnow()
    async with SessionLocal() as db:
        ali = User(telegram_id=111, username="AliDev", first_name="Ali", cefr_level="A2", onboarded=True)
        vali = User(
            telegram_id=222, username=None, first_name="Vali", cefr_level="B1",
            plan="pro", plan_expires_at=now + timedelta(days=2),
            created_at=now - timedelta(days=20), last_active_at=now - timedelta(days=10),
        )
        db.add_all([ali, vali])
        await db.flush()
        db.add(Session(user_id=ali.id, started_at=now, duration_seconds=600))
        db.add(Payment(user_id=vali.id, plan="pro", amount=29000, status="approved", decided_at=now))
        db.add(Payment(user_id=ali.id, plan="max", amount=69000, status="review"))
        await db.commit()


async def test_find_user_by_id_username_and_search() -> None:
    await _seed()
    async with SessionLocal() as db:
        assert (await admin_stats.find_user(db, "111")).first_name == "Ali"  # type: ignore[union-attr]
        assert (await admin_stats.find_user(db, "@alidev")).telegram_id == 111  # type: ignore[union-attr]
        assert await admin_stats.find_user(db, "@nobody") is None
        assert [u.first_name for u in await admin_stats.search_users(db, "val")] == ["Vali"]


async def test_set_plan_with_custom_days_and_revoke() -> None:
    await _seed()
    now = billing.utcnow()
    async with SessionLocal() as db:
        ali = await admin_stats.find_user(db, "111")
        assert ali is not None
        exp = admin_stats.set_plan(ali, "pro", 7, now)
        assert exp == now + timedelta(days=7) and billing.effective_plan(ali, now).code == "pro"
        assert admin_stats.set_plan(ali, "pro", 7, now) == now + timedelta(days=14)  # ustiga qo'shiladi
        assert admin_stats.set_plan(ali, "free") is None
        assert billing.effective_plan(ali, now).code == "free" and ali.plan_expires_at is None
        card = await admin_stats.user_card(db, ali, now)
        assert "Ali" in card and "Sessiyalar: 1" in card


async def test_collect_stats_counts() -> None:
    await _seed()
    async with SessionLocal() as db:
        s = await admin_stats.collect_stats(db)
    assert s.users_total == 2 and s.users_onboarded == 1
    assert s.new_7d == 1 and s.active_7d == 1
    assert s.sessions_today == 1 and s.minutes_today == 10
    assert s.pro_active == 1 and s.expiring_3d == 1
    assert s.revenue_total == 29000 and s.revenue_today == 29000 and s.payments_review == 1
    assert s.levels == {"A2": 1, "B1": 1}
    text = admin_stats.format_stats(s)
    assert "29 000 so'm" in text and "Tekshiruvda: <b>1</b>" in text
