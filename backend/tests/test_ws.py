"""2. WebSocket: auth, "bitta aktiv sessiya" lock va to'liq oqim (soxta Gemini bilan)."""
from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from typing import Any
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient
from google.genai import types
from sqlalchemy import select
from starlette.websockets import WebSocketDisconnect

from app.api import ws as ws_module
from app.database import SessionLocal
from app.main import app
from app.models import Error, Session, User
from app.redis_client import SessionLock
from tests.conftest import make_init_data

AUDIO_OUT = b"\x01\x00" * 480


class FakeLive:
    """Gemini Live sessiyasining soxtasi: bitta skriptlangan turn, keyin jim kutadi."""

    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []
        self.tool_responses: list[Any] = []
        self._served = False
        self._forever = asyncio.Event()

    async def send_realtime_input(self, **kwargs: Any) -> None:
        self.sent.append(kwargs)

    async def send_tool_response(self, *, function_responses: Any) -> None:
        self.tool_responses.append(function_responses)

    async def receive(self):
        if self._served:
            await self._forever.wait()
            return
        self._served = True
        sc = types.LiveServerContent
        yield types.LiveServerMessage(server_content=sc(input_transcription=types.Transcription(text="I am go to school")))
        yield types.LiveServerMessage(
            server_content=sc(
                model_turn=types.Content(
                    parts=[types.Part(inline_data=types.Blob(data=AUDIO_OUT, mime_type="audio/pcm;rate=24000"))]
                )
            )
        )
        yield types.LiveServerMessage(server_content=sc(output_transcription=types.Transcription(text="Kichik xato. Say: I am going.")))
        yield types.LiveServerMessage(
            tool_call=types.LiveServerToolCall(
                function_calls=[
                    types.FunctionCall(
                        id="call-1",
                        name="log_error",
                        args={"error_type": "grammar", "wrong": "I am go", "correct": "I am going", "severity": "medium"},
                    )
                ]
            )
        )
        yield types.LiveServerMessage(server_content=sc(turn_complete=True))


@pytest.fixture
def fake_live(monkeypatch):
    holder: dict[str, FakeLive] = {}

    @asynccontextmanager
    async def factory(prompt: str, mode: str):
        live = FakeLive()
        holder["live"] = live
        holder["prompt"] = prompt  # type: ignore[assignment]
        yield live, "fake-live-model"

    monkeypatch.setattr(ws_module, "live_session_factory", factory)
    return holder


def _recv_until(conn, stop_type: str, limit: int = 50) -> tuple[list[dict], list[bytes]]:
    events: list[dict] = []
    audio: list[bytes] = []
    for _ in range(limit):
        msg = conn.receive()
        if msg.get("bytes") is not None:
            audio.append(msg["bytes"])
            continue
        if msg.get("text") is None:
            break
        event = json.loads(msg["text"])
        events.append(event)
        if event["type"] == stop_type:
            break
    return events, audio


def test_ws_rejects_missing_or_bad_init_data() -> None:
    with TestClient(app) as client:
        for url in ("/ws/audio", "/ws/audio?init_data=foo%3Dbar"):
            with client.websocket_connect(url) as conn:
                assert conn.receive_json() == {
                    "type": "server_error",
                    "code": "unauthorized",
                    "message": "Telegram orqali qayta oching",
                }
                with pytest.raises(WebSocketDisconnect) as exc:
                    conn.receive_json()
                assert exc.value.code == 4401


def test_ws_rejects_second_active_session(fake_live) -> None:
    with TestClient(app) as client:
        raw = make_init_data(9001, "Bobur")
        init = quote(raw, safe="")
        # Avval foydalanuvchini yaratish uchun REST chaqiramiz, keyin lock'ni "band" qilamiz
        assert client.get("/api/me", headers={"Authorization": f"tma {raw}"}).status_code == 200

        async def _user_id() -> int:
            async with SessionLocal() as db:
                return (await db.execute(select(User.id).where(User.telegram_id == 9001))).scalar_one()

        user_id = client.portal.call(_user_id)
        lock = SessionLock(user_id, ttl=60)
        assert client.portal.call(lock.acquire)

        with client.websocket_connect(f"/ws/audio?init_data={init}") as conn:
            event = conn.receive_json()
            assert event["type"] == "server_error" and event["code"] == "active_session"
            with pytest.raises(WebSocketDisconnect) as exc:
                conn.receive_json()
            assert exc.value.code == 4429
        client.portal.call(lock.release)


def test_ws_full_flow_persists_to_db(fake_live) -> None:
    with TestClient(app) as client:
        init = quote(make_init_data(9002, "Malika"), safe="")
        with client.websocket_connect(f"/ws/audio?init_data={init}&mode=free") as conn:
            ready = conn.receive_json()
            assert ready["type"] == "ready" and ready["level"] == "A1" and ready["model"] == "fake-live-model"

            events, audio = _recv_until(conn, "turn_complete")
            if not any(e["type"] == "error" for e in events):
                # Tool chaqiruvlari alohida worker'da — "error" turn_complete'dan keyin kelishi mumkin
                more, _ = _recv_until(conn, "error")
                events += more
            types_ = [e["type"] for e in events]
            assert "user_transcript" in types_ and "adam_transcript" in types_ and "error" in types_
            assert audio == [AUDIO_OUT]
            error_event = next(e for e in events if e["type"] == "error")
            assert error_event["correct"] == "I am going"

            # Mikrofondan PCM chunk va boshqaruv xabarlari
            conn.send_bytes(b"\x00\x00" * 1600)
            conn.send_json({"type": "ping", "t": 1})
            assert conn.receive_json() == {"type": "pong", "t": 1}

            conn.send_json({"type": "end"})
            summary = conn.receive_json()
            assert summary["type"] == "session_end"
            assert summary["errors_count"] == 1
            assert summary["sentences_spoken"] == 1

        live = fake_live["live"]
        assert any("text" in s for s in live.sent)  # kickoff trigger
        assert any("audio" in s for s in live.sent)  # PCM uzatildi
        fr = live.tool_responses[0][0]
        assert fr.id == "call-1" and fr.response == {"result": "ok"}
        assert "Malika" in fake_live["prompt"]

        async def _check() -> tuple[Session, list[Error]]:
            async with SessionLocal() as db:
                s = (await db.execute(select(Session))).scalar_one()
                e = (await db.execute(select(Error))).scalars().all()
                return s, list(e)

        session, errors = client.portal.call(_check)
        assert session.ended_at is not None and session.sentences_spoken == 1
        assert len(errors) == 1 and errors[0].session_id == session.id

        # Lock bo'shatilgan — yangi sessiya ochish mumkin
        with client.websocket_connect(f"/ws/audio?init_data={init}") as conn:
            ready = conn.receive_json()
            assert ready["type"] == "ready"
            # Testda SESSION_TIMEOUT=120 = Free limiti; sessiya hech qachon limitdan uzun bo'lmaydi
            assert ready["quota"]["plan"] == "free" and ready["quota"]["limit_seconds"] == 120
            assert ready["timeout_seconds"] <= 120
            conn.send_json({"type": "end"})
            _recv_until(conn, "session_end")


def test_ws_free_limit_exhausted_blocks_session(fake_live) -> None:
    with TestClient(app) as client:
        raw = make_init_data(9003, "Sardor")
        init = quote(raw, safe="")
        assert client.get("/api/me", headers={"Authorization": f"tma {raw}"}).status_code == 200

        async def _exhaust() -> None:
            from app.services import billing

            async with SessionLocal() as db:
                u = (await db.execute(select(User).where(User.telegram_id == 9003))).scalar_one()
                billing.start_usage(u)
                billing.add_usage(u, 130)
                await db.commit()

        client.portal.call(_exhaust)
        me = client.get("/api/me", headers={"Authorization": f"tma {raw}"}).json()
        assert me["plan"]["plan"] == "free" and me["plan"]["remaining_seconds"] == 0

        with client.websocket_connect(f"/ws/audio?init_data={init}") as conn:
            event = conn.receive_json()
            assert event["type"] == "limit_reached" and event["plan"] == "free"
            assert event["resets_at"] is not None
            with pytest.raises(WebSocketDisconnect) as exc:
                conn.receive_json()
            assert exc.value.code == 4402
        assert "live" not in fake_live  # Gemini'ga umuman ulanmadi

        async def _flag() -> bool:
            async with SessionLocal() as db:
                return (await db.execute(select(User.limit_notify).where(User.telegram_id == 9003))).scalar_one()

        assert client.portal.call(_flag) is True
