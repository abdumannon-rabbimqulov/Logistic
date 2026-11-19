"""Support mikroservizining RabbitMQ qatlami.

Topologiya asosiy ilovadagi `services/queue.py` bilan BIR XIL bo'lishi shart —
exchange nomi, turi (`topic`), `durable` bayrog'i va navbat nomlari. Aks holda
AMQP `PRECONDITION_FAILED` bilan kanalni yopadi (bir xil nomli exchange boshqa
parametrlar bilan qayta e'lon qilinsa).

Bu fayl asosiy loyihadan hech narsa import qilmaydi: mikroserviz mustaqil
deploy qilinadigan bo'lishi kerak. Umumiy narsa faqat SHARTNOMA — exchange nomi va
routing key'lar (`tests/test_event_contract.py` ikkala tomonni ham qulflab turadi).
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Awaitable, Callable, Optional

import aio_pika
from aio_pika.abc import (
    AbstractIncomingMessage,
    AbstractRobustChannel,
    AbstractRobustConnection,
    AbstractRobustExchange,
)

from support_service.config import RABBITMQ_URL

logger = logging.getLogger(__name__)

# Shartnoma — `contracts/events.py` (core bilan yagona manba; image'ga ko'chiriladi).
from contracts.events import (  # noqa: E402
    EVENT_ORDER_STATUS_CHANGED,
    EVENT_ORDER_TRIP_STARTED,
    EVENT_ORDER_TRUCK_ASSIGNED,
    EVENT_ORDER_WAYPOINT_CHANGED,
    EVENT_SUPPORT_TICKET_CREATED,
    EVENT_SUPPORT_TICKET_REPLIED,
    EVENT_SUPPORT_TICKET_STATUS_CHANGED,
    EVENTS_EXCHANGE,
    SUPPORT_EVENTS_PATTERN,
    SUPPORT_EVENTS_QUEUE,
    SUPPORT_NOTIFICATIONS_PATTERN,
    SUPPORT_NOTIFICATIONS_QUEUE,
    build_envelope,
)

PREFETCH = 10

_connection: Optional[AbstractRobustConnection] = None
_channel: Optional[AbstractRobustChannel] = None
_exchange: Optional[AbstractRobustExchange] = None
_lock = asyncio.Lock()


class QueueUnavailable(RuntimeError):
    pass


async def get_channel() -> AbstractRobustChannel:
    global _connection, _channel, _exchange

    if _channel is not None and not _channel.is_closed:
        return _channel

    async with _lock:
        if _channel is not None and not _channel.is_closed:
            return _channel
        try:
            if _connection is None or _connection.is_closed:
                _connection = await aio_pika.connect_robust(RABBITMQ_URL)
            _channel = await _connection.channel(publisher_confirms=True)
            await _channel.set_qos(prefetch_count=PREFETCH)
            _exchange = await _declare(_channel)
        except Exception as exc:
            _channel = None
            _exchange = None
            raise QueueUnavailable(f"RabbitMQ'ga ulanib bo'lmadi: {exc}") from exc
        return _channel


async def _declare(channel: AbstractRobustChannel) -> AbstractRobustExchange:
    exchange = await channel.declare_exchange(
        EVENTS_EXCHANGE, aio_pika.ExchangeType.TOPIC, durable=True
    )

    order_events = await channel.declare_queue(SUPPORT_EVENTS_QUEUE, durable=True)
    await order_events.bind(exchange, SUPPORT_EVENTS_PATTERN)

    notifications = await channel.declare_queue(SUPPORT_NOTIFICATIONS_QUEUE, durable=True)
    await notifications.bind(exchange, SUPPORT_NOTIFICATIONS_PATTERN)

    return exchange


async def publish_event(event: str, payload: dict[str, Any]) -> bool:
    """Hodisa yuboradi. Istisno tashlamaydi — murojaat allaqachon bazaga yozilgan,
    broker o'chgani uchun foydalanuvchiga xato qaytarish noto'g'ri bo'lardi."""
    envelope = build_envelope(event, payload)
    message = aio_pika.Message(
        body=json.dumps(envelope, separators=(",", ":"), default=str).encode(),
        content_type="application/json",
        delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
        message_id=envelope["event_id"],
        type=event,
    )
    try:
        await get_channel()
        if _exchange is None:
            raise QueueUnavailable("events exchange e'lon qilinmagan")
        await _exchange.publish(message, routing_key=event)
        return True
    except Exception:
        logger.exception("Hodisa yuborilmadi: %s", event)
        return False


async def consume_order_events(
    handler: Callable[[str, dict[str, Any]], Awaitable[None]]
) -> str:
    """`support.order_events` navbatini tinglaydi; consumer tag qaytaradi.

    Xato bo'lganda xabar `requeue=False` bilan tashlanadi: murojaatga izoh qo'shish —
    kritik bo'lmagan yon ta'sir, cheksiz qayta urinish navbatni tiqib qo'yardi.
    """

    async def _on_message(message: AbstractIncomingMessage) -> None:
        async with message.process(requeue=False):
            try:
                envelope = json.loads(message.body)
                event = str(envelope["event"])
                data = envelope.get("data") or {}
            except (ValueError, KeyError, TypeError):
                logger.exception("Yaroqsiz hodisa tashlandi: %r", message.body[:200])
                return
            try:
                await handler(event, data)
            except Exception:
                logger.exception("Hodisani qayta ishlashda xato: %s", event)

    channel = await get_channel()
    queue = await channel.get_queue(SUPPORT_EVENTS_QUEUE)
    tag = await queue.consume(_on_message)
    logger.info("Buyurtma hodisalari tinglanmoqda: '%s'", SUPPORT_EVENTS_QUEUE)
    return tag


async def close_queue() -> None:
    global _connection, _channel, _exchange
    try:
        if _connection is not None and not _connection.is_closed:
            await _connection.close()
    except Exception:
        logger.exception("RabbitMQ ulanishini yopishda xato")
    finally:
        _connection = None
        _channel = None
        _exchange = None
