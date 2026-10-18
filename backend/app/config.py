"""Ilova sozlamalari: barcha qiymatlar .env / muhit o'zgaruvchilaridan o'qiladi."""
from __future__ import annotations

from datetime import timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """Pydantic-settings orqali tiplangan konfiguratsiya."""

    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8-sig",
        extra="ignore",
        case_sensitive=False,
    )

    TELEGRAM_BOT_TOKEN: str = ""
    GEMINI_API_KEY: str = ""
    DATABASE_URL: str = ""
    REDIS_URL: str = ""
    FRONTEND_URL: str = "http://localhost:5173"
    WEBAPP_URL: str = ""
    BACKEND_URL: str = ""
    ENVIRONMENT: Literal["development", "production", "test"] = "development"
    BOT_MODE: Literal["auto", "polling", "webhook", "disabled"] = "auto"
    WEBHOOK_SECRET: str = ""

    GEMINI_MODEL: str = "gemini-3.8-live"
    GEMINI_FALLBACK_MODELS: str = "gemini-2.5-flash-native-audio-preview-12-2025"
    GEMINI_VOICE: str = "Puck"
    GEMINI_TEXT_MODEL: str = "gemini-3.8-flash"
    GEMINI_TEXT_FALLBACK_MODEL: str = "gemini-2.5-flash"

    # To'lov / tariflar
    RECEIPT_GEMINI_API_KEY: str = ""
    RECEIPT_MODEL: str = "gemini-3.1-pro-preview"
    RECEIPT_FALLBACK_MODEL: str = "gemini-3.8-flash"
    PAYMENT_CARD_NUMBER: str = ""
    PAYMENT_CARD_HOLDER: str = ""
    PRO_PRICE: int = 29000
    MAX_PRICE: int = 69000
    PLAN_DAYS: int = Field(default=30, ge=1)
    ADMIN_IDS: str = ""
    RECEIPT_AUTO_MIN_CONFIDENCE: float = Field(default=0.85, ge=0, le=1)
    RECEIPT_MAX_AGE_HOURS: int = Field(default=72, ge=1)
    DAILY_LESSON_HOUR: int = Field(default=9, ge=0, le=23)
    TZ_OFFSET_HOURS: int = Field(default=5, ge=-12, le=14)  # Toshkent = UTC+5

    LOG_LEVEL: str = "INFO"
    SESSION_TIMEOUT_SECONDS: int = Field(default=900, ge=60, le=3600)
    WS_RATE_LIMIT_PER_MINUTE: int = Field(default=10, ge=1)
    INIT_DATA_MAX_AGE: int = Field(default=86400, ge=60)
    ALLOW_DEV_AUTH: bool = False

    @field_validator("FRONTEND_URL", "WEBAPP_URL", "BACKEND_URL")
    @classmethod
    def _strip_slash(cls, v: str) -> str:
        return v.strip().rstrip("/")

    @property
    def local_tz(self) -> timezone:
        return timezone(timedelta(hours=self.TZ_OFFSET_HOURS))

    @property
    def admin_ids(self) -> set[int]:
        return {int(x) for x in self.ADMIN_IDS.replace(" ", "").split(",") if x.lstrip("-").isdigit()}

    @property
    def card_last4(self) -> str:
        digits = "".join(ch for ch in self.PAYMENT_CARD_NUMBER if ch.isdigit())
        return digits[-4:]

    @property
    def receipt_api_key(self) -> str:
        """Chek uchun alohida kalit; berilmagan bo'lsa asosiy kalit."""
        return self.RECEIPT_GEMINI_API_KEY or self.GEMINI_API_KEY

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT == "production"

    @property
    def dev_auth_enabled(self) -> bool:
        """Dev-auth faqat development muhitida va aniq yoqilganda ishlaydi."""
        return self.ALLOW_DEV_AUTH and self.ENVIRONMENT != "production"

    @property
    def gemini_models(self) -> list[str]:
        """Asosiy + zaxira Live modellar ro'yxati (takrorlarsiz, tartib saqlanadi)."""
        models = [self.GEMINI_MODEL] + [m.strip() for m in self.GEMINI_FALLBACK_MODELS.split(",")]
        return list(dict.fromkeys(m for m in models if m))

    @property
    def effective_bot_mode(self) -> str:
        if not self.TELEGRAM_BOT_TOKEN or self.ENVIRONMENT == "test":
            return "disabled"
        if self.BOT_MODE == "auto":
            return "webhook" if self.is_production else "polling"
        return self.BOT_MODE

    @property
    def cors_origins(self) -> list[str]:
        origins = [self.FRONTEND_URL]
        if not self.is_production:
            origins += ["http://localhost:5173", "http://127.0.0.1:5173"]
        return list(dict.fromkeys(o for o in origins if o))

    @property
    def database_url(self) -> str:
        """DATABASE_URL ni async drayverga moslaydi; bo'sh bo'lsa lokal SQLite."""
        url = self.DATABASE_URL.strip()
        if not url:
            return f"sqlite+aiosqlite:///{(BASE_DIR / 'adam.db').as_posix()}"
        if url.startswith("postgres://"):
            url = "postgresql+asyncpg://" + url[len("postgres://"):]
        elif url.startswith("postgresql://"):
            url = "postgresql+asyncpg://" + url[len("postgresql://"):]
        if url.startswith("postgresql+asyncpg://"):
            parts = urlsplit(url)
            query = [(k, v) for k, v in parse_qsl(parts.query) if k not in ("sslmode", "channel_binding")]
            if not any(k == "prepared_statement_cache_size" for k, _ in query):
                query.append(("prepared_statement_cache_size", "0"))
            url = urlunsplit(parts._replace(query=urlencode(query)))
        return url

    @property
    def database_requires_ssl(self) -> bool:
        raw = self.DATABASE_URL.lower()
        return "sslmode=require" in raw or "neon.tech" in raw or "supabase" in raw


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
