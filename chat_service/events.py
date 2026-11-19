"""`order.*` hodisalarini suhbatlarga qo'llash (RabbitMQ iste'molchisi).

Qoidalarning o'zi `domain.apply_order_event` da; bu yerda faqat bazadan o'qish va
yozish. Bir buyurtma uchun parallel ikki hodisa kelsa (prefetch > 1) `order_id`
UNIQUE cheklovi dublikat suhbatni to'xtatadi — o'shanda bir marta qayta urinamiz.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from chat_service import domain
from chat_service.config import READONLY_AFTER_S
from chat_service.db import session_factory
from chat_service.models import Conversation
from chat_service.realtime import get_broadcaster

logger = logging.getLogger(__name__)


async def handle_order_event(
    event: str, data: dict[str, Any], occurred_at: Optional[datetime] = None
) -> Optional[Conversation]:
    ev = domain.parse_order_event(event, data, occurred_at)
    if ev is None:
        return None

    for attempt in range(2):
        async with session_factory()() as db:
            conv = (
                await db.execute(select(Conversation).where(Conversation.order_id == ev.order_id))
            ).scalar_one_or_none()
            before = _snapshot(conv)
            updated = domain.apply_order_event(conv, ev, readonly_after_s=READONLY_AFTER_S)
            if updated is None:
                return conv
            if conv is None:
                db.add(updated)
            try:
                await db.commit()
            except IntegrityError:
                await db.rollback()
                if attempt == 0:
                    continue
                raise
            await db.refresh(updated)
            if before != _snapshot(updated):
                logger.info(
                    "Chat #%s (order #%s): %s → holat=%s, driver=%s/%s",
                    updated.id, ev.order_id, ev.new_status or event, updated.status,
                    updated.driver_id, updated.driver_user_id,
                )
                # Ochiq sahifalar sarlavhasini (yopildi / haydovchi almashdi) yangilasin.
                await get_broadcaster().publish(
                    {before[0] if before else None, before[1] if before else None,
                     updated.sender_user_id, updated.driver_user_id},
                    {"type": "conversation.updated", "order_id": updated.order_id},
                )
            return updated
    return None


def _snapshot(conv: Optional[Conversation]) -> Optional[tuple]:
    if conv is None:
        return None
    return (conv.sender_user_id, conv.driver_user_id, conv.driver_id, conv.status, conv.readonly_at)
