"""Redis kliyenti: sessiya lock, rate-limit va kesh.

REDIS_URL bo'sh bo'lsa (lokal dev / testlar) jarayon ichidagi `MemoryRedis`
ishlatiladi. U faqat bitta jarayon uchun to'g'ri ishlaydi — production'da
albatta haqiqiy Redis (Upstash / Railway) ulang.
"""
from __future__ import annotations

import asyncio
import logging
import secrets
import time
from typing import Protocol

from app.config import settings

logger = logging.getLogger(__name__)

_RELEASE_LUA = """
if redis.call('get', KEYS[1]) == ARGV[1] then
  return redis.call('del', KEYS[1])
end
return 0
"""

_REFRESH_LUA = """
if redis.call('get', KEYS[1]) == ARGV[1] then
  return redis.call('expire', KEYS[1], ARGV[2])
end
return 0
"""


class KV(Protocol):
    async def set_nx(self, key: str, value: str, ttl: int) -> bool: ...
    async def get(self, key: str) -> str | None: ...
    async def delete_if_equals(self, key: str, value: str) -> bool: ...
    async def expire_if_equals(self, key: str, value: str, ttl: int) -> bool: ...
    async def incr_with_ttl(self, key: str, ttl: int) -> int: ...
    async def ping(self) -> bool: ...
    async def close(self) -> None: ...


class MemoryRedis:
    """Redis'ning kerakli qismini jarayon xotirasida taqlid qiladi."""

    def __init__(self) -> None:
        self._data: dict[str, tuple[str, float]] = {}
        self._lock = asyncio.Lock()

    def _alive(self, key: str) -> str | None:
        item = self._data.get(key)
        if item is None:
            return None
        value, expires = item
        if expires and expires < time.monotonic():
            self._data.pop(key, None)
            return None
        return value

    async def set_nx(self, key: str, value: str, ttl: int) -> bool:
        async with self._lock:
            if self._alive(key) is not None:
                return False
            self._data[key] = (value, time.monotonic() + ttl)
            return True

    async def get(self, key: str) -> str | None:
        async with self._lock:
            return self._alive(key)

    async def delete_if_equals(self, key: str, value: str) -> bool:
        async with self._lock:
            if self._alive(key) == value:
                self._data.pop(key, None)
                return True
            return False

    async def expire_if_equals(self, key: str, value: str, ttl: int) -> bool:
        async with self._lock:
            if self._alive(key) == value:
                self._data[key] = (value, time.monotonic() + ttl)
                return True
            return False

    async def incr_with_ttl(self, key: str, ttl: int) -> int:
        async with self._lock:
            current = self._alive(key)
            if current is None:
                self._data[key] = ("1", time.monotonic() + ttl)
                return 1
            new = int(current) + 1
            self._data[key] = (str(new), self._data[key][1])
            return new

    async def ping(self) -> bool:
        return True

    async def close(self) -> None:
        self._data.clear()


class RealRedis:
    """redis.asyncio ustidagi yupqa qatlam (atomik Lua skriptlar bilan)."""

    def __init__(self, url: str) -> None:
        from redis.asyncio import Redis

        self._r = Redis.from_url(url, decode_responses=True, health_check_interval=30)
        self._release = self._r.register_script(_RELEASE_LUA)
        self._refresh = self._r.register_script(_REFRESH_LUA)

    async def set_nx(self, key: str, value: str, ttl: int) -> bool:
        return bool(await self._r.set(key, value, nx=True, ex=ttl))

    async def get(self, key: str) -> str | None:
        return await self._r.get(key)

    async def delete_if_equals(self, key: str, value: str) -> bool:
        return bool(await self._release(keys=[key], args=[value]))

    async def expire_if_equals(self, key: str, value: str, ttl: int) -> bool:
        return bool(await self._refresh(keys=[key], args=[value, ttl]))

    async def incr_with_ttl(self, key: str, ttl: int) -> int:
        async with self._r.pipeline(transaction=True) as pipe:
            pipe.incr(key)
            pipe.expire(key, ttl, nx=True)
            count, _ = await pipe.execute()
        return int(count)

    async def ping(self) -> bool:
        return bool(await self._r.ping())

    async def close(self) -> None:
        await self._r.aclose()


_kv: KV | None = None


async def init_redis() -> KV:
    """Redis'ga ulanadi; URL bo'lmasa xotiradagi fallback'ni qaytaradi."""
    global _kv
    if settings.REDIS_URL:
        kv = RealRedis(settings.REDIS_URL)
        await kv.ping()
        logger.info("Redis ulandi")
    else:
        if settings.is_production:
            logger.warning("REDIS_URL yo'q! Production'da in-memory lock faqat 1 jarayonda ishlaydi.")
        kv = MemoryRedis()
        logger.info("Redis o'rniga in-memory fallback ishlatilmoqda")
    _kv = kv
    return kv


def get_redis() -> KV:
    global _kv
    if _kv is None:
        _kv = MemoryRedis()
    return _kv


async def close_redis() -> None:
    global _kv
    if _kv is not None:
        await _kv.close()
        _kv = None


# ---------------------------------------------------------------- lock / limit

def _lock_key(user_id: int) -> str:
    return f"adam:session_lock:{user_id}"


class SessionLock:
    """"Bir foydalanuvchi = bitta aktiv sessiya" uchun tokenli Redis lock."""

    def __init__(self, user_id: int, ttl: int) -> None:
        self.key = _lock_key(user_id)
        self.ttl = ttl
        self.token = secrets.token_hex(16)

    async def acquire(self) -> bool:
        return await get_redis().set_nx(self.key, self.token, self.ttl)

    async def refresh(self) -> bool:
        return await get_redis().expire_if_equals(self.key, self.token, self.ttl)

    async def release(self) -> None:
        try:
            await get_redis().delete_if_equals(self.key, self.token)
        except Exception:  # noqa: BLE001
            logger.exception("Lock bo'shatishda xato: %s", self.key)


async def hit_rate_limit(user_id: int, limit: int, window: int = 60) -> bool:
    """True qaytarsa — limit oshib ketgan."""
    try:
        count = await get_redis().incr_with_ttl(f"adam:ws_rate:{user_id}:{int(time.time() // window)}", window)
    except Exception:  # noqa: BLE001
        logger.exception("Rate-limit tekshiruvida xato")
        return False
    return count > limit
