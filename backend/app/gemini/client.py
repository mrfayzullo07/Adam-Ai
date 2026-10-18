"""google-genai Live API kliyenti: konfiguratsiya va model fallback bilan ulanish."""
from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager
from functools import lru_cache
from typing import Any, Protocol

from google import genai
from google.genai import types

from app.config import settings
from app.gemini.tools import get_tools

logger = logging.getLogger(__name__)


class LiveSessionProtocol(Protocol):
    """Biz ishlatadigan Live sessiya interfeysi (testlarda soxtasi bilan almashtiriladi)."""

    async def send_realtime_input(self, **kwargs: Any) -> None: ...
    async def send_tool_response(self, *, function_responses: Any) -> None: ...
    def receive(self) -> AsyncIterator[types.LiveServerMessage]: ...


class GeminiUnavailableError(RuntimeError):
    """Hech bir Live modelga ulanib bo'lmadi."""


@lru_cache
def get_client() -> genai.Client:
    if not settings.GEMINI_API_KEY:
        raise GeminiUnavailableError("GEMINI_API_KEY sozlanmagan")
    return genai.Client(api_key=settings.GEMINI_API_KEY)


def build_live_config(system_prompt: str, mode: str, voice: str | None = None) -> types.LiveConnectConfig:
    """Live sessiya konfiguratsiyasi.

    mode="free": Gemini avtomatik VAD (foydalanuvchi Adam'ni bo'lishi mumkin).
    mode="ptt":  avtomatik VAD o'chiq — client activity_start/activity_end yuboradi.
    """
    vad = types.AutomaticActivityDetection(disabled=True)
    if mode != "ptt":
        # LOW start: shovqin/aks-sado Adam'ni bo'lib qo'ymasin; uzun silence: boshlovchi o'ylab gapiradi
        vad = types.AutomaticActivityDetection(
            disabled=False,
            start_of_speech_sensitivity=types.StartSensitivity.START_SENSITIVITY_LOW,
            end_of_speech_sensitivity=types.EndSensitivity.END_SENSITIVITY_LOW,
            prefix_padding_ms=300,
            silence_duration_ms=1300,
        )
    return types.LiveConnectConfig(
        response_modalities=[types.Modality.AUDIO],
        speech_config=types.SpeechConfig(
            voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice or settings.GEMINI_VOICE)
            )
        ),
        system_instruction=types.Content(role="system", parts=[types.Part(text=system_prompt)]),
        # Foydalanuvchi o'zbekcha va inglizcha gapiradi
        input_audio_transcription=types.AudioTranscriptionConfig(language_codes=["uz-UZ", "en-US"]),
        output_audio_transcription=types.AudioTranscriptionConfig(),
        tools=get_tools(),
        realtime_input_config=types.RealtimeInputConfig(automatic_activity_detection=vad),
    )


@asynccontextmanager
async def open_live_session(system_prompt: str, mode: str) -> AsyncIterator[tuple[LiveSessionProtocol, str]]:
    """Konfiguratsiyadagi modellarni ketma-ket sinab ko'radi; (session, model) qaytaradi."""
    client = get_client()
    config = build_live_config(system_prompt, mode)
    last_exc: Exception | None = None
    async with AsyncExitStack() as stack:
        session: LiveSessionProtocol | None = None
        used_model = ""
        for model in settings.gemini_models:
            try:
                session = await stack.enter_async_context(client.aio.live.connect(model=model, config=config))
                used_model = model
                logger.info("Gemini Live ulandi: model=%s mode=%s", model, mode)
                break
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                logger.warning("Gemini model '%s' ga ulanib bo'lmadi: %s", model, exc)
        if session is None:
            raise GeminiUnavailableError(f"Live modellarga ulanib bo'lmadi: {last_exc}") from last_exc
        yield session, used_model
