"""Real vaqt hodisalari: `/support/ws` ulanishlariga fan-out.

Kanallar:
    support:u:<user_id>  — murojaat egasiga tegishli hodisalar
    support:staff        — barcha xodimlar (admin/menejer) uchun

`REDIS_URL` berilgan bo'lsa Redis pub/sub ishlatiladi — support bir nechta nusxada
ishlasa ham hodisa hamma ulanishga yetadi. Aks holda jarayon ichidagi broker.

Nashr qilish hech qachon xato tashlamaydi: bu yon ta'sir, asosiy yozuv
allaqachon bazada.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Iterable, Optional, Protocol

from support_service.config import REDIS_URL

logger = logging.getLogger(__name__)

STAFF_CHANNEL = "support:staff"


def user_channel(user_id: int) -> str:
    return f"support:u:{user_id}"


class Subscription(Protocol):
    async def get(self, timeout: float) -> Optional[dict[str, Any]]: ...

    async def close(self) -> None: ...


class Broker(Protocol):
    async def publish(self, channel: str, payload: dict[str, Any]) -> None: ...

    async def subscribe(self, channels: Iterable[str]) -> Subscription: ...


class _MemorySubscription:
    def __init__(self, broker: "MemoryBroker", channels: list[str]) -> None:
        self._broker = broker
        self._channels = channels
        self.queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=1000)

    async def get(self, timeout: float) -> Optional[dict[str, Any]]:
        try:
            return await asyncio.wait_for(self.queue.get(), timeout)
        except asyncio.TimeoutError:
            return None

    async def close(self) -> None:
        for channel in self._channels:
            subs = self._broker.subscribers.get(channel)
            if subs is not None:
                subs.discard(self)
                if not subs:
                    self._broker.subscribers.pop(channel, None)


class MemoryBroker:
    def __init__(self) -> None:
        self.subscribers: dict[str, set[_MemorySubscription]] = {}

    async def publish(self, channel: str, payload: dict[str, Any]) -> None:
        for sub in list(self.subscribers.get(channel, ())):
            try:
                sub.queue.put_nowait(payload)
            except asyncio.QueueFull:
                logger.warning("WS navbati to'lgan — hodisa tashlandi (%s)", channel)

    async def subscribe(self, channels: Iterable[str]) -> _MemorySubscription:
        channel_list = list(channels)
        sub = _MemorySubscription(self, channel_list)
        for channel in channel_list:
            self.subscribers.setdefault(channel, set()).add(sub)
        return sub


class _RedisSubscription:
    def __init__(self, pubsub: Any) -> None:
        self._pubsub = pubsub

    async def get(self, timeout: float) -> Optional[dict[str, Any]]:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while True:
            remaining = deadline - loop.time()
            if remaining <= 0:
                return None
            message = await self._pubsub.get_message(
                ignore_subscribe_messages=True, timeout=remaining
            )
            if message is None:
                continue
            try:
                return json.loads(message["data"])
            except (TypeError, ValueError):
                logger.warning("Yaroqsiz WS hodisasi tashlandi")

    async def close(self) -> None:
        try:
            await self._pubsub.unsubscribe()
            await self._pubsub.aclose()
        except Exception:
            pass


class RedisBroker:
    def __init__(self, url: str) -> None:
        from redis import asyncio as aioredis

        self.client = aioredis.from_url(url, decode_responses=True)

    async def publish(self, channel: str, payload: dict[str, Any]) -> None:
        await self.client.publish(channel, json.dumps(payload, default=str))

    async def subscribe(self, channels: Iterable[str]) -> _RedisSubscription:
        pubsub = self.client.pubsub()
        await pubsub.subscribe(*channels)
        return _RedisSubscription(pubsub)

    async def close(self) -> None:
        try:
            await self.client.aclose()
        except Exception:
            pass


_broker: Optional[Broker] = None


def get_broker() -> Broker:
    global _broker
    if _broker is None:
        _broker = RedisBroker(REDIS_URL) if REDIS_URL else MemoryBroker()
    return _broker


def set_broker(broker: Optional[Broker]) -> None:
    global _broker
    _broker = broker


async def close_broker() -> None:
    global _broker
    if isinstance(_broker, RedisBroker):
        await _broker.close()
    _broker = None


async def publish(
    event_type: str, payload: dict[str, Any], *, user_id: Optional[int], staff: bool = True
) -> None:
    """Hodisani murojaat egasiga va (kerak bo'lsa) xodimlarga yuboradi."""
    message = {"type": event_type, **payload}
    channels: list[str] = []
    if user_id is not None:
        channels.append(user_channel(user_id))
    if staff:
        channels.append(STAFF_CHANNEL)
    broker = get_broker()
    for channel in channels:
        try:
            await broker.publish(channel, message)
        except Exception:
            logger.warning("Real vaqt hodisasi yuborilmadi (%s)", channel, exc_info=True)
