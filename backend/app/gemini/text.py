"""Oddiy (Live bo'lmagan) Gemini chaqiruvlari: guruh repetitori, kunlik dars, chek tahlili."""
from __future__ import annotations

import logging
from functools import lru_cache
from typing import Any

from google import genai
from google.genai import types

from app.config import settings

logger = logging.getLogger(__name__)


class GeminiTextError(RuntimeError):
    pass


@lru_cache(maxsize=4)
def _client(api_key: str) -> genai.Client:
    return genai.Client(api_key=api_key)


async def generate(
    contents: Any,
    *,
    models: list[str],
    api_key: str | None = None,
    config: types.GenerateContentConfig | None = None,
) -> types.GenerateContentResponse:
    """Modellarni ketma-ket sinaydi; birinchi muvaffaqiyatli javobni qaytaradi."""
    key = api_key or settings.GEMINI_API_KEY
    if not key:
        raise GeminiTextError("Gemini API kaliti sozlanmagan")
    client = _client(key)
    last_exc: Exception | None = None
    for model in dict.fromkeys(m for m in models if m):
        try:
            return await client.aio.models.generate_content(model=model, contents=contents, config=config)
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            logger.warning("Gemini %s ishlamadi: %s", model, exc)
    raise GeminiTextError(str(last_exc) if last_exc else "Model topilmadi")


def text_models() -> list[str]:
    return [settings.GEMINI_TEXT_MODEL, settings.GEMINI_TEXT_FALLBACK_MODEL]


def receipt_models() -> list[str]:
    return [settings.RECEIPT_MODEL, settings.RECEIPT_FALLBACK_MODEL]
