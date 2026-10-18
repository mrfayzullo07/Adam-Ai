"""Client WebSocket <-> Gemini Live ko'prigi.

Uchta parallel vazifa:
  upstream   — client'dan PCM (16 kHz) va JSON boshqaruv xabarlari -> Gemini
  downstream — Gemini'dan audio (24 kHz), transkriptlar, tool_call -> client
  watchdog   — sessiya timeout'i, ogohlantirish va Redis lock yangilash
Birinchisi tugashi bilan qolganlari bekor qilinadi va tugash sababi qaytariladi.

Client protokoli:
  client -> server: binary = PCM16 16 kHz mono;
                    JSON {"type": "activity_start" | "activity_end" | "audio_stream_end" | "text" | "end" | "ping"}
  server -> client: binary = PCM16 24 kHz mono;
                    JSON {"type": "ready" | "user_transcript" | "adam_transcript" | "turn_complete" |
                          "interrupted" | "error" | "scores" | "vocabulary" | "level_update" |
                          "warning" | "session_end" | "server_error" | "pong"}
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

from fastapi import WebSocket
from google.genai import types
from starlette.websockets import WebSocketDisconnect, WebSocketState

from app.gemini.client import LiveSessionProtocol
from app.gemini.prompt import SESSION_START_TRIGGER
from app.gemini.tools import DbFactory, handle_function_call, response_scheduling
from app.redis_client import SessionLock
from app.services.session_service import SessionState
from app.utils.audio import INPUT_MIME, is_valid_pcm16_chunk

logger = logging.getLogger(__name__)

WARNING_BEFORE_END = 60  # soniya
TOOL_DRAIN_TIMEOUT = 3.0
LOCK_REFRESH_INTERVAL = 30
WATCHDOG_TICK = 1.0
MAX_TEXT_INPUT = 500


class ClientSender:
    """WebSocket'ga parallel yozishni ketma-ketlashtiradi (bir nechta task yuboradi)."""

    def __init__(self, ws: WebSocket) -> None:
        self._ws = ws
        self._lock = asyncio.Lock()

    @property
    def open(self) -> bool:
        return self._ws.client_state == WebSocketState.CONNECTED and self._ws.application_state == WebSocketState.CONNECTED

    async def json(self, payload: dict[str, Any]) -> None:
        if not self.open:
            return
        async with self._lock:
            try:
                await self._ws.send_text(json.dumps(payload, ensure_ascii=False, default=str))
            except (WebSocketDisconnect, RuntimeError):
                pass

    async def bytes(self, data: bytes) -> None:
        if not self.open or not data:
            return
        async with self._lock:
            try:
                await self._ws.send_bytes(data)
            except (WebSocketDisconnect, RuntimeError):
                pass


class AdamBridge:
    """Bitta sessiya uchun client va Gemini o'rtasidagi oqimni boshqaradi."""

    def __init__(
        self,
        *,
        ws: WebSocket,
        live: LiveSessionProtocol,
        state: SessionState,
        db_factory: DbFactory,
        timeout_seconds: int,
        lock: SessionLock | None = None,
        warning_message: str = "Sessiya 1 daqiqadan keyin tugaydi",
    ) -> None:
        self.ws = ws
        self.send = ClientSender(ws)
        self.live = live
        self.state = state
        self.db_factory = db_factory
        self.timeout = timeout_seconds
        self.lock = lock
        self.warning_message = warning_message
        self.started = time.monotonic()
        self._adam_turn_active = False
        self._adam_buffer = ""
        self._warned = False
        self._tool_queue: asyncio.Queue[types.LiveServerToolCall] = asyncio.Queue()

    # ------------------------------------------------------------------ public
    async def run(self) -> str:
        """Sessiyani boshlaydi va tugash sababini qaytaradi."""
        await self._kickoff()
        tasks = {
            asyncio.create_task(self._upstream(), name="adam-upstream"),
            asyncio.create_task(self._downstream(), name="adam-downstream"),
            asyncio.create_task(self._watchdog(), name="adam-watchdog"),
            asyncio.create_task(self._tool_worker(), name="adam-tools"),
        }
        reason = "unknown"
        try:
            done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                exc = task.exception()
                if exc is not None:
                    logger.error("%s xato bilan tugadi: %r", task.get_name(), exc, exc_info=exc)
                    reason = "gemini_error" if task.get_name() == "adam-downstream" else "error"
                else:
                    reason = task.result()
            # Navbatdagi tool chaqiruvlari (xatolar, ballar) DB'ga yozilib ulgursin
            try:
                await asyncio.wait_for(self._tool_queue.join(), TOOL_DRAIN_TIMEOUT)
            except asyncio.TimeoutError:
                logger.warning("Tool navbati vaqtida tugamadi: %s", self.state.session_id)
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
        self._end_adam_turn()
        logger.info("Bridge tugadi: session=%s reason=%s", self.state.session_id, reason)
        return reason

    # ------------------------------------------------------------------ kickoff
    async def _kickoff(self) -> None:
        """Adam birinchi bo'lib salomlashishi uchun trigger yuboradi."""
        try:
            if self.state.mode == "ptt":
                await self.live.send_realtime_input(activity_start=types.ActivityStart())
                await self.live.send_realtime_input(text=SESSION_START_TRIGGER)
                await self.live.send_realtime_input(activity_end=types.ActivityEnd())
            else:
                await self.live.send_realtime_input(text=SESSION_START_TRIGGER)
        except Exception:  # noqa: BLE001
            logger.exception("Kickoff trigger yuborilmadi")

    # ------------------------------------------------------------------ upstream
    async def _upstream(self) -> str:
        while True:
            message = await self.ws.receive()
            if message["type"] == "websocket.disconnect":
                return "client_disconnected"
            data: bytes | None = message.get("bytes")
            if data is not None:
                if is_valid_pcm16_chunk(data):
                    await self.live.send_realtime_input(audio=types.Blob(data=data, mime_type=INPUT_MIME))
                continue
            text: str | None = message.get("text")
            if text is None:
                continue
            try:
                payload = json.loads(text)
            except json.JSONDecodeError:
                continue
            if not isinstance(payload, dict):
                continue
            result = await self._handle_control(payload)
            if result is not None:
                return result

    async def _handle_control(self, payload: dict[str, Any]) -> str | None:
        kind = payload.get("type")
        if kind == "end":
            return "client_end"
        if kind == "ping":
            await self.send.json({"type": "pong", "t": payload.get("t")})
        elif kind == "activity_start" and self.state.mode == "ptt":
            await self.live.send_realtime_input(activity_start=types.ActivityStart())
        elif kind == "activity_end" and self.state.mode == "ptt":
            await self.live.send_realtime_input(activity_end=types.ActivityEnd())
        elif kind == "audio_stream_end" and self.state.mode != "ptt":
            await self.live.send_realtime_input(audio_stream_end=True)
        elif kind == "text":
            text = " ".join(str(payload.get("text", "")).split())[:MAX_TEXT_INPUT]
            if text:
                self.state.add_user_transcript(text + " ")
                if self.state.mode == "ptt":
                    await self.live.send_realtime_input(activity_start=types.ActivityStart())
                    await self.live.send_realtime_input(text=text)
                    await self.live.send_realtime_input(activity_end=types.ActivityEnd())
                else:
                    await self.live.send_realtime_input(text=text)
        return None

    # ------------------------------------------------------------------ downstream
    async def _downstream(self) -> str:
        while True:
            got_any = False
            async for msg in self.live.receive():
                got_any = True
                await self._handle_server_message(msg)
            if not got_any:
                return "gemini_closed"

    async def _handle_server_message(self, msg: types.LiveServerMessage) -> None:
        sc = msg.server_content
        if sc is not None:
            if sc.input_transcription is not None and sc.input_transcription.text:
                if self._adam_turn_active:
                    self._end_adam_turn()
                self.state.add_user_transcript(sc.input_transcription.text)
                await self.send.json({"type": "user_transcript", "text": sc.input_transcription.text})

            if sc.model_turn is not None and sc.model_turn.parts:
                for part in sc.model_turn.parts:
                    if part.inline_data is not None and part.inline_data.data:
                        self._begin_adam_turn()
                        await self.send.bytes(part.inline_data.data)

            if sc.output_transcription is not None and sc.output_transcription.text:
                self._begin_adam_turn()
                self._adam_buffer += sc.output_transcription.text
                await self.send.json({"type": "adam_transcript", "text": sc.output_transcription.text})

            if sc.interrupted:
                self._end_adam_turn()
                await self.send.json({"type": "interrupted"})

            if sc.turn_complete:
                self._end_adam_turn()
                self.state.flush_user_turn()
                await self.send.json(
                    {
                        "type": "turn_complete",
                        "stats": {
                            "sentences_spoken": self.state.sentences_spoken,
                            "words_spoken": self.state.words_spoken,
                        },
                    }
                )

        if msg.tool_call is not None and msg.tool_call.function_calls:
            # DB yozuvlari audio oqimini to'xtatmasligi uchun alohida worker'da bajariladi
            self._tool_queue.put_nowait(msg.tool_call)

        if msg.tool_call_cancellation is not None:
            logger.info("Tool call bekor qilindi: %s", msg.tool_call_cancellation.ids)

        if msg.go_away is not None:
            time_left = getattr(msg.go_away, "time_left", None)
            logger.warning("Gemini go_away: time_left=%s", time_left)
            await self.send.json(
                {"type": "warning", "code": "go_away", "message": "Ulanish tez orada yangilanadi", "time_left": str(time_left)}
            )

    async def _tool_worker(self) -> str:
        while True:
            tool_call = await self._tool_queue.get()
            try:
                await self._handle_tool_call(tool_call)
            except Exception:  # noqa: BLE001
                logger.exception("Tool call bajarilmadi")
            finally:
                self._tool_queue.task_done()

    async def _handle_tool_call(self, tool_call: types.LiveServerToolCall) -> None:
        responses: list[types.FunctionResponse] = []
        for fc in tool_call.function_calls or []:
            result = await handle_function_call(fc.name or "", fc.args, self.state, self.db_factory)
            responses.append(
                types.FunctionResponse(
                    id=fc.id,
                    name=fc.name,
                    response=result.response,
                    scheduling=response_scheduling(fc.name or ""),
                )
            )
            for event in result.events:
                await self.send.json(event)
        if responses:
            await self.live.send_tool_response(function_responses=responses)

    def _begin_adam_turn(self) -> None:
        if not self._adam_turn_active:
            self._adam_turn_active = True
            self.state.flush_user_turn()

    def _end_adam_turn(self) -> None:
        if self._adam_buffer:
            self.state.add_adam_line(self._adam_buffer)
            self._adam_buffer = ""
        self._adam_turn_active = False

    # ------------------------------------------------------------------ watchdog
    async def _watchdog(self) -> str:
        last_refresh = time.monotonic()
        while True:
            await asyncio.sleep(WATCHDOG_TICK)
            now = time.monotonic()
            elapsed = now - self.started
            remaining = self.timeout - elapsed
            if remaining <= 0:
                return "timeout"
            if not self._warned and remaining <= WARNING_BEFORE_END:
                self._warned = True
                await self.send.json(
                    {
                        "type": "warning",
                        "code": "timeout_soon",
                        "message": self.warning_message,
                        "seconds_left": int(remaining),
                    }
                )
            if self.lock is not None and now - last_refresh >= LOCK_REFRESH_INTERVAL:
                last_refresh = now
                if not await self.lock.refresh():
                    logger.warning("Sessiya lock yo'qoldi: %s", self.lock.key)
                    return "lock_lost"
