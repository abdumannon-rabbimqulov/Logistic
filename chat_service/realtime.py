"""Real vaqt: Redis pub/sub orqali WebSocket'larga hodisa tarqatish.

Kanal — FOYDALANUVCHI bo'yicha (`chat:user:<id>`), suhbat bo'yicha emas: bitta
ulanish foydalanuvchining hamma suhbatlarini oladi (badge'lar uchun ham), va bir
nechta `chat` replikasi bo'lsa ham hodisa kerakli ulanishga yetadi.

Hodisa shakli (WS orqali mijozga aynan shu boradi):
    {"type": "message.new" | "message.edited" | "message.read" | "typing",
     "order_id": int, ...}

Onlayn holat: har ulanish `chat:online:<user_id>` hisoblagichini oshiradi (TTL
bilan — jarayon yiqilsa ham "abadiy onlayn" qolib ketmaydi). Hodisada
`recipient_online` sifatida yuboriladi: qabul qiluvchi chatni ochib turgan bo'lsa,
Telegram bildirishnomasi kerak emas.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Iterable, Optional, Protocol

from chat_service.config import REDIS_URL

logger = logging.getLogger(__name__)

ONLINE_TTL_S = 90


def user_channel(user_id: int) -> str:
    return f"chat:user:{user_id}"


def online_key(user_id: int) -> str:
    return f"chat:online:{user_id}"


class Broadcaster(Protocol):
    async def publish(self, user_ids: Iterable[Optional[int]], event: dict[str, Any]) -> None: ...

    async def is_online(self, user_id: Optional[int]) -> bool: ...


class RedisBroadcaster:
    def __init__(self, url: str = REDIS_URL) -> None:
        import redis.asyncio as aioredis

        self.redis = aioredis.from_url(url, decode_responses=True)

    async def publish(self, user_ids: Iterable[Optional[int]], event: dict[str, Any]) -> None:
        payload = json.dumps(event, default=str, separators=(",", ":"))
        for uid in {u for u in user_ids if u is not None}:
            try:
                await self.redis.publish(user_channel(uid), payload)
            except Exception:
                # Real vaqt — yon ta'sir: xabar bazada, mijoz qayta ulanishda oladi.
                logger.exception("Redis publish xatosi (user=%s)", uid)

    async def is_online(self, user_id: Optional[int]) -> bool:
        if user_id is None:
            return False
        try:
            return int(await self.redis.get(online_key(user_id)) or 0) > 0
        except Exception:
            return False

    async def mark_online(self, user_id: int, delta: int) -> None:
        key = online_key(user_id)
        try:
            value = await self.redis.incrby(key, delta)
            if value <= 0:
                await self.redis.delete(key)
            else:
                await self.redis.expire(key, ONLINE_TTL_S)
        except Exception:
            logger.exception("Onlayn holatni yangilab bo'lmadi (user=%s)", user_id)

    async def touch_online(self, user_id: int) -> None:
        try:
            await self.redis.expire(online_key(user_id), ONLINE_TTL_S)
        except Exception:
            pass

    async def close(self) -> None:
        try:
            await self.redis.aclose()
        except Exception:
            pass


class MemoryBroadcaster:
    """Testlar uchun: yuborilgan hodisalarni ro'yxatda saqlaydi."""

    def __init__(self) -> None:
        self.sent: list[tuple[int, dict[str, Any]]] = []
        self.online: set[int] = set()

    async def publish(self, user_ids: Iterable[Optional[int]], event: dict[str, Any]) -> None:
        for uid in {u for u in user_ids if u is not None}:
            self.sent.append((uid, json.loads(json.dumps(event, default=str))))

    async def is_online(self, user_id: Optional[int]) -> bool:
        return user_id in self.online


_broadcaster: Optional[Broadcaster] = None


def get_broadcaster() -> Broadcaster:
    global _broadcaster
    if _broadcaster is None:
        _broadcaster = RedisBroadcaster()
    return _broadcaster


def set_broadcaster(broadcaster: Optional[Broadcaster]) -> None:
    global _broadcaster
    _broadcaster = broadcaster
