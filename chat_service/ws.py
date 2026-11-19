"""`/chat/ws?token=` — real vaqt kanali.

Server → mijoz (Redis `chat:user:<id>` kanalidan):
    message.new | message.edited | message.read | typing | conversation.updated
Mijoz → server:
    {"type": "typing", "order_id": N}   — sherigiga "yozmoqda…" (2 s da ko'pi bilan bir marta)
    {"type": "ping"}                   — {"type": "pong"}; onlayn TTL'ni yangilaydi

Qayta ulanish: WS'ning o'zi tarixni saqlamaydi. Mijoz ulanish ochilgach
`GET /chat/orders/<id>/sync?after_id=<oxirgi id>&since=<server_time>` bilan
uzilish paytida o'tkazib yuborilganlarni oladi (`useChatSocket.ts`).

Yopilish kodlari: 4401 — token yaroqsiz/muddati tugadi (mijoz tokenni yangilab
qayta ulanadi), 1013 — real vaqt vaqtincha mavjud emas (Redis yo'q).
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect
from sqlalchemy import select

from chat_service import domain
from chat_service.auth import InvalidToken, principal_from_token
from chat_service.db import session_factory
from chat_service.models import Conversation
from chat_service.realtime import RedisBroadcaster, get_broadcaster, user_channel

logger = logging.getLogger(__name__)

router = APIRouter()

TYPING_MIN_INTERVAL_S = 2.0


async def _peer_for(order_id: int, user_id: int) -> Optional[int]:
    """Typing uchun: foydalanuvchi shu suhbat ishtirokchisi va yoza oladimi."""
    async with session_factory()() as db:
        conv = (
            await db.execute(select(Conversation).where(Conversation.order_id == order_id))
        ).scalar_one_or_none()
    if conv is None or not domain.is_participant(conv, user_id):
        return None
    if domain.write_block_reason(conv, datetime.now(timezone.utc)):
        return None
    return domain.peer_user_id(conv, user_id)


@router.websocket("/chat/ws")
async def chat_ws(websocket: WebSocket, token: str = Query("")):
    try:
        principal = principal_from_token(token)
    except InvalidToken:
        await websocket.close(code=4401)
        return

    broadcaster = get_broadcaster()
    if not isinstance(broadcaster, RedisBroadcaster):
        await websocket.close(code=1013)
        return

    await websocket.accept()
    pubsub = broadcaster.redis.pubsub()
    try:
        await pubsub.subscribe(user_channel(principal.user_id))
    except Exception:
        # Redis yo'q — mijoz 1013 ni ko'rib keyinroq qayta ulanadi; REST ishlayveradi.
        logger.warning("Chat WS: Redis'ga obuna bo'lib bo'lmadi (user=%s)", principal.user_id, exc_info=True)
        await websocket.close(code=1013)
        return
    await broadcaster.mark_online(principal.user_id, +1)

    peers: dict[int, Optional[int]] = {}
    last_typing: dict[int, float] = {}

    async def pump_redis() -> None:
        async for item in pubsub.listen():
            if item.get("type") != "message":
                continue
            await websocket.send_text(item["data"])

    async def pump_client() -> None:
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except ValueError:
                continue
            kind = msg.get("type")
            if kind == "ping":
                await broadcaster.touch_online(principal.user_id)
                await websocket.send_text('{"type":"pong"}')
            elif kind == "typing":
                try:
                    order_id = int(msg.get("order_id"))
                except (TypeError, ValueError):
                    continue
                now = time.monotonic()
                if now - last_typing.get(order_id, 0.0) < TYPING_MIN_INTERVAL_S:
                    continue
                last_typing[order_id] = now
                if order_id not in peers:
                    peers[order_id] = await _peer_for(order_id, principal.user_id)
                peer = peers[order_id]
                if peer is not None:
                    await broadcaster.publish(
                        [peer], {"type": "typing", "order_id": order_id, "user_id": principal.user_id}
                    )

    async def expire_token() -> None:
        if principal.exp is None:
            await asyncio.Event().wait()
        await asyncio.sleep(max(0.0, principal.exp - time.time()))
        await websocket.close(code=4401)

    tasks = [asyncio.create_task(t()) for t in (pump_redis, pump_client, expire_token)]
    try:
        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            exc = task.exception()
            if exc and not isinstance(exc, (WebSocketDisconnect, RuntimeError)):
                logger.warning("Chat WS xatosi (user=%s): %r", principal.user_id, exc)
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        try:
            await pubsub.unsubscribe()
            await pubsub.aclose()
        except Exception:
            pass
        await broadcaster.mark_online(principal.user_id, -1)
