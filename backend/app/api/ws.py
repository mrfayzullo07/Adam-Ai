"""/ws/audio — real-time ovozli sessiya endpointi.

Oqim: initData auth -> rate-limit -> Redis lock -> sessions yozuvi -> kontekst ->
Gemini Live ulanish -> AdamBridge -> yakunlash (DB) -> lock bo'shatish.

Maxsus yopilish kodlari (client qayta ulanmasligi kerak):
  4401 — initData yaroqsiz       4429 — aktiv sessiya bor / rate-limit
  4503 — Gemini mavjud emas      4402 — tarif limiti tugagan
  1000 — normal yakun
"""
from __future__ import annotations

import logging
import time
from typing import Any, Literal

from fastapi import APIRouter, Query, WebSocket
from starlette.websockets import WebSocketState

from app.api.auth import InitDataError, parse_auth, upsert_user
from app.config import settings
from app.database import SessionLocal
from app.gemini.client import GeminiUnavailableError, open_live_session
from app.gemini.prompt import build_system_prompt
from app.gemini.session import AdamBridge
from app.lessons.catalog import get_topic
from app.models import Session as SessionModel
from app.models import User
from app.redis_client import SessionLock, hit_rate_limit
from app.services import billing
from app.services import level as lvl
from app.services.session_service import SessionState, create_session, finalize_session, load_user_context

logger = logging.getLogger(__name__)
router = APIRouter(tags=["ws"])

CLOSE_UNAUTHORIZED = 4401
CLOSE_BUSY = 4429
CLOSE_UNAVAILABLE = 4503
CLOSE_LIMIT = 4402

# Testlarda soxta Live sessiya bilan almashtiriladi
live_session_factory = open_live_session


async def _reject(ws: WebSocket, code: int, error: str, message: str) -> None:
    try:
        await ws.send_json({"type": "server_error", "code": error, "message": message})
        await ws.close(code=code)
    except Exception:  # noqa: BLE001
        pass


def _limit_event(user: User) -> dict[str, Any]:
    q = billing.quota_dict(user)
    plan = q["plan"]
    if plan == "free":
        msg = "Bepul vaqtingiz tugadi. Davom etish uchun Pro'ga o'ting yoki limit yangilanishini kuting."
    else:
        msg = "Tarifingizdagi vaqt limiti tugadi. Limit yangilanishini kuting yoki Max'ga o'ting."
    return {"type": "limit_reached", "message": msg, **q}


async def _safe_close(ws: WebSocket, code: int = 1000) -> None:
    if ws.application_state == WebSocketState.CONNECTED and ws.client_state == WebSocketState.CONNECTED:
        try:
            await ws.close(code=code)
        except Exception:  # noqa: BLE001
            pass


@router.websocket("/ws/audio")
async def ws_audio(
    ws: WebSocket,
    init_data: str = Query(default=""),
    mode: Literal["free", "ptt"] = Query(default="free"),
    topic: str = Query(default=""),
) -> None:
    await ws.accept()
    found_topic = get_topic(topic)
    topic_id = found_topic[1].id if found_topic else None

    # 1. Auth
    try:
        tg_user = parse_auth(init_data)
    except InitDataError as exc:
        logger.info("WS auth rad etildi: %s", exc)
        await _reject(ws, CLOSE_UNAUTHORIZED, "unauthorized", "Telegram orqali qayta oching")
        return

    async with SessionLocal() as db:
        user = await upsert_user(db, tg_user)
        # 1b. Tarif limiti
        quota = billing.get_quota(user)
        if quota.exhausted:
            billing.mark_limit_hit(user)
            await db.commit()
            try:
                await ws.send_json(_limit_event(user))
            except Exception:  # noqa: BLE001
                pass
            await _safe_close(ws, CLOSE_LIMIT)
            return

    session_timeout = settings.SESSION_TIMEOUT_SECONDS
    limit_bound = quota.remaining_seconds is not None and quota.remaining_seconds < session_timeout
    if limit_bound:
        assert quota.remaining_seconds is not None
        session_timeout = max(1, quota.remaining_seconds)

    # 2. Rate-limit va "bitta aktiv sessiya" lock
    if await hit_rate_limit(user.id, settings.WS_RATE_LIMIT_PER_MINUTE):
        await _reject(ws, CLOSE_BUSY, "rate_limited", "Juda ko'p urinish. Bir daqiqadan so'ng qayta urinib ko'ring")
        return
    lock = SessionLock(user.id, ttl=settings.SESSION_TIMEOUT_SECONDS + 120)
    if not await lock.acquire():
        await _reject(ws, CLOSE_BUSY, "active_session", "Sizda allaqachon aktiv sessiya bor (boshqa qurilmada?)")
        return

    state: SessionState | None = None
    bridge_started = False
    bridge_started_at: float | None = None
    close_code = 1000
    limit_hit = False
    try:
        # 3-4. Sessiya yozuvi va dinamik kontekst
        async with SessionLocal() as db:
            db_user = await db.get(User, user.id)
            if db_user is not None:
                billing.start_usage(db_user)
                await db.commit()
            session_row = await create_session(db, user, mode)
            recent_errors, last_summary = await load_user_context(db, user.id)

        state = SessionState(
            session_id=session_row.id,
            user_id=user.id,
            user_name=user.first_name,
            level=lvl.normalize_level(user.cefr_level),
            level_progress=user.level_progress,
            mode=mode,
            started_at=session_row.started_at,
            placement=bool(user.needs_placement),
        )
        prompt = build_system_prompt(
            user_name=user.first_name,
            cefr_level=state.level,
            level_progress=state.level_progress,
            recent_errors=recent_errors,
            last_session_summary=last_summary,
            mode=mode,
            explain_lang=user.explain_lang,
            speech_pace=user.speech_pace,
            goal=user.goal,
            placement=state.placement,
            topic_id=topic_id,
        )

        # 5-6. Gemini Live + asosiy sikl
        async with live_session_factory(prompt, mode) as (live, model):
            bridge_started = True
            bridge_started_at = time.monotonic()
            await ws.send_json(
                {
                    "type": "ready",
                    "session_id": str(state.session_id),
                    "mode": mode,
                    "model": model,
                    "timeout_seconds": session_timeout,
                    "limit_bound": limit_bound,
                    "quota": billing.quota_dict(user),
                    "level": state.level,
                    "next_level": lvl.next_level(state.level),
                    "progress": state.level_progress,
                    "user_name": user.first_name,
                    "placement": state.placement,
                    "topic": (
                        {"id": found_topic[1].id, "title": found_topic[1].title, "emoji": found_topic[1].emoji}
                        if found_topic
                        else None
                    ),
                }
            )
            bridge = AdamBridge(
                ws=ws,
                live=live,
                state=state,
                db_factory=SessionLocal,
                timeout_seconds=session_timeout,
                lock=lock,
                warning_message=(
                    "Tarif vaqtingiz 1 daqiqadan keyin tugaydi" if limit_bound else "Sessiya 1 daqiqadan keyin tugaydi"
                ),
            )
            reason = await bridge.run()
            if reason == "timeout":
                limit_hit = limit_bound
                logger.info("Sessiya timeout: %s (limit=%s)", state.session_id, limit_hit)

    except GeminiUnavailableError as exc:
        logger.error("Gemini mavjud emas: %s", exc)
        close_code = CLOSE_UNAVAILABLE
        await _reject(ws, CLOSE_UNAVAILABLE, "gemini_unavailable", "Adam hozir band. Birozdan so'ng qayta urinib ko'ring")
    except Exception:  # noqa: BLE001
        logger.exception("WS sessiyada kutilmagan xato")
        close_code = 1011
        if ws.client_state == WebSocketState.CONNECTED:
            try:
                await ws.send_json({"type": "server_error", "code": "internal", "message": "Server xatosi"})
            except Exception:  # noqa: BLE001
                pass
    finally:
        # 7. Yakunlash: DB yozuvlari + lock bo'shatish
        try:
            if state is not None:
                async with SessionLocal() as db:
                    if bridge_started:
                        # Sarflangan vaqtni tarif limitiga yozamiz
                        used = int(round(time.monotonic() - bridge_started_at)) if bridge_started_at else 0
                        db_user = await db.get(User, state.user_id)
                        if db_user is not None:
                            quota_after = billing.add_usage(db_user, used)
                            if limit_hit or quota_after.exhausted:
                                billing.mark_limit_hit(db_user)
                                limit_hit = True
                            await db.commit()
                            if limit_hit and ws.client_state == WebSocketState.CONNECTED:
                                try:
                                    await ws.send_json(_limit_event(db_user))
                                except Exception:  # noqa: BLE001
                                    pass
                        summary = await finalize_session(db, state)
                        if summary and ws.client_state == WebSocketState.CONNECTED:
                            try:
                                await ws.send_json(summary)
                            except Exception:  # noqa: BLE001
                                pass
                    else:
                        # Gemini'ga ulanmagan bo'sh sessiya statistikani buzmasligi uchun o'chiriladi
                        row = await db.get(SessionModel, state.session_id)
                        if row is not None:
                            await db.delete(row)
                            await db.commit()
        except Exception:  # noqa: BLE001
            logger.exception("Sessiyani yakunlashda xato")
        finally:
            await lock.release()
            await _safe_close(ws, close_code)
