"""Transactional outbox — biznes hodisalari yo'qolmasligi uchun.

Muammo (ilgari): hodisa commit'dan KEYIN to'g'ridan-to'g'ri RabbitMQ'ga yuborilardi
va `publish_event` xatoni yutib yuborardi. Broker shu lahzada o'chiq bo'lsa yoki
jarayon commit va publish orasida yiqilsa, hodisa izsiz yo'qolardi: support izohi,
senderga Telegram xabari, kelajakdagi chat/tracking servislari uni hech qachon
olmasdi.

Yechim:
  1. `enqueue(db, event, payload)` hodisani `outbox_events` jadvaliga yozadi —
     biznes o'zgarishi bilan BITTA tranzaksiyada (chaqiruvchi commit qiladi).
     Commit bo'lmasa, hodisa ham yo'q; commit bo'lsa, hodisa albatta bor.
  2. `relay_once()` (dispatch-worker ichida har soniyada) yuborilmagan yozuvlarni
     `FOR UPDATE SKIP LOCKED` bilan oladi, RabbitMQ'ga yuboradi va belgilaydi.
     Bir nechta worker parallel ishlasa ham bir yozuv ikki marta olinmaydi.

Yetkazish kafolati — "kamida bir marta" (at-least-once): relay yuborgach belgilashdan
oldin yiqilsa, hodisa qayta ketadi. Iste'molchilar konvertdagi `event_id` bo'yicha
takrorni aniqlay oladi.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import BigInteger, DateTime, Index, SmallInteger, String, Text, delete, func, select, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from config.base import Base
from services import queue

logger = logging.getLogger(__name__)

RELAY_BATCH = 100
# Shuncha urinishdan keyin yozuv "o'lik" hisoblanadi va avtomatik qayta yuborilmaydi
# (admin qo'lda ko'rib chiqadi: `SELECT * FROM outbox_events WHERE attempts >= 20`).
MAX_ATTEMPTS = 20
# Yuborilgan yozuvlar shuncha saqlanadi (diagnostika uchun), keyin o'chiriladi.
KEEP_PUBLISHED = timedelta(days=7)


class OutboxEvent(Base):
    __tablename__ = "outbox_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(String(36), unique=True, nullable=False)
    event: Mapped[str] = mapped_column(String(64), nullable=False)
    # To'liq konvert (`queue.build_event`): event, event_id, occurred_at, data.
    envelope: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    attempts: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0, server_default="0")
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    __table_args__ = (
        # Relay faqat yuborilmaganlarni o'qiydi — qisman indeks kichik va tez.
        Index(
            "ix_outbox_events_unpublished",
            "id",
            postgresql_where=text("published_at IS NULL"),
        ),
    )


def enqueue(db: AsyncSession, event: str, payload: dict[str, Any]) -> OutboxEvent:
    """Hodisani joriy tranzaksiyaga qo'shadi. Commit'ni CHAQIRUVCHI qiladi."""
    envelope = queue.build_event(event, _jsonable(payload))
    row = OutboxEvent(event_id=envelope["event_id"], event=event, envelope=envelope, attempts=0)
    db.add(row)
    return row


def _jsonable(value: Any) -> Any:
    """JSONB ga yoziladigan qiymatlar: Decimal/datetime/enum -> str."""
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    enum_value = getattr(value, "value", None)
    if isinstance(enum_value, (str, int)):
        return enum_value
    return str(value)


async def relay_once(db: AsyncSession, *, batch: int = RELAY_BATCH) -> int:
    """Yuborilmagan hodisalarni RabbitMQ'ga yuboradi. Qaytaradi: yuborilganlar soni."""
    result = await db.execute(
        select(OutboxEvent)
        .where(OutboxEvent.published_at.is_(None), OutboxEvent.attempts < MAX_ATTEMPTS)
        .order_by(OutboxEvent.id)
        .limit(batch)
        .with_for_update(skip_locked=True)
    )
    rows = list(result.scalars().all())
    if not rows:
        await db.rollback()
        return 0

    sent = 0
    now = datetime.now(timezone.utc)
    for row in rows:
        try:
            await queue.publish_envelope(row.envelope)
        except Exception as exc:
            row.attempts += 1
            row.last_error = str(exc)[:1000]
            logger.warning("Outbox #%s (%s) yuborilmadi: %s", row.id, row.event, exc)
            # Broker ishlamayapti — qolganlarini ham hozir urinish befoyda.
            break
        row.published_at = now
        row.attempts += 1
        sent += 1
    await db.commit()
    return sent


async def purge_published(db: AsyncSession) -> int:
    """Eski yuborilgan yozuvlarni o'chiradi (jadval cheksiz o'smasligi uchun)."""
    cutoff = datetime.now(timezone.utc) - KEEP_PUBLISHED
    result = await db.execute(
        delete(OutboxEvent).where(OutboxEvent.published_at.is_not(None), OutboxEvent.published_at < cutoff)
    )
    await db.commit()
    return result.rowcount or 0
