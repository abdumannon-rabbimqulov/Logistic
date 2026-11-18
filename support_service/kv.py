"""Kichik kalit-qiymat qatlami: kesh va rate-limit hisoblagichlari.

`REDIS_URL` berilgan bo'lsa — Redis (bir nechta nusxa bir xil hisoblagichni
ko'radi). Berilmasa — jarayon xotirasi: bitta nusxali lokal ishga tushirish va
testlar uchun. Redis vaqtincha yiqilsa xato TASHLANMAYDI: kesh "topilmadi",
rate-limit esa "o'tkazib yuborildi" deb hisoblanadi — support asosiy funksiyasi
(murojaat yozish) Redis'ga qaram bo'lmasin.
"""

from __future__ import annotations

import logging
import time
from typing import Optional, Protocol

from support_service.config import REDIS_URL

logger = logging.getLogger(__name__)


class KV(Protocol):
    async def get(self, key: str) -> Optional[str]: ...

    async def set(self, key: str, value: str, ttl: int) -> None: ...

    async def delete(self, key: str) -> None: ...

    async def hit(self, key: str, window: int) -> tuple[int, int]:
        """Hisoblagichni bittaga oshiradi. (joriy qiymat, oyna tugashiga soniya)."""
        ...


class MemoryKV:
    def __init__(self) -> None:
        self._data: dict[str, tuple[str, float]] = {}

    def _alive(self, key: str) -> Optional[tuple[str, float]]:
        item = self._data.get(key)
        if item is None:
            return None
        if item[1] <= time.monotonic():
            self._data.pop(key, None)
            return None
        return item

    async def get(self, key: str) -> Optional[str]:
        item = self._alive(key)
        return item[0] if item else None

    async def set(self, key: str, value: str, ttl: int) -> None:
        self._data[key] = (value, time.monotonic() + ttl)

    async def delete(self, key: str) -> None:
        self._data.pop(key, None)

    async def hit(self, key: str, window: int) -> tuple[int, int]:
        item = self._alive(key)
        now = time.monotonic()
        if item is None:
            self._data[key] = ("1", now + window)
            return 1, window
        count = int(item[0]) + 1
        self._data[key] = (str(count), item[1])
        return count, max(1, int(item[1] - now))

    def clear(self) -> None:
        self._data.clear()


class RedisKV:
    def __init__(self, url: str) -> None:
        from redis import asyncio as aioredis

        self.client = aioredis.from_url(url, decode_responses=True)

    async def get(self, key: str) -> Optional[str]:
        try:
            return await self.client.get(key)
        except Exception:
            logger.warning("Redis GET xatosi (%s)", key, exc_info=True)
            return None

    async def set(self, key: str, value: str, ttl: int) -> None:
        try:
            await self.client.set(key, value, ex=ttl)
        except Exception:
            logger.warning("Redis SET xatosi (%s)", key, exc_info=True)

    async def delete(self, key: str) -> None:
        try:
            await self.client.delete(key)
        except Exception:
            logger.warning("Redis DEL xatosi (%s)", key, exc_info=True)

    async def hit(self, key: str, window: int) -> tuple[int, int]:
        try:
            pipe = self.client.pipeline(transaction=True)
            # NX: oyna faqat birinchi urinishda boshlanadi (fixed window).
            pipe.set(key, 0, ex=window, nx=True)
            pipe.incr(key)
            pipe.ttl(key)
            _, count, ttl = await pipe.execute()
            return int(count), max(1, int(ttl))
        except Exception:
            logger.warning("Redis rate-limit xatosi (%s) — o'tkazib yuborildi", key, exc_info=True)
            return 0, window

    async def close(self) -> None:
        try:
            await self.client.aclose()
        except Exception:
            pass


_kv: Optional[KV] = None


def get_kv() -> KV:
    global _kv
    if _kv is None:
        _kv = RedisKV(REDIS_URL) if REDIS_URL else MemoryKV()
    return _kv


def set_kv(kv: Optional[KV]) -> None:
    """Testlar uchun: toza xotira variantini o'rnatish."""
    global _kv
    _kv = kv


async def close_kv() -> None:
    global _kv
    if isinstance(_kv, RedisKV):
        await _kv.close()
    _kv = None
