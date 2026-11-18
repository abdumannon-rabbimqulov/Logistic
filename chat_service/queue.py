"""Chat mikroservizining RabbitMQ qatlami (`support_service/queue.py` naqshi).

Topologiya (`logistika.events`, topic, durable — core bilan BIR XIL parametrlar):

    order.*  → chat.order_events   — shu xizmat o'qiydi (suhbatni ochish/yopish)
    chat.*   → chat.notifications  — `workers/events_worker.py` o'qiydi (Telegram)

Ikkala navbat ham shu yerda, ham events_worker'da e'lon qilinadi (idempotent):
qaysi biri birinchi ko'tarilsa ham, ikkinchisi kechiksa hodisa yo'qolmaydi.
Core'ning `services/queue.py` si hali `chat.order_events` ni e'lon qilmaydi —
chat birinchi marta ko'tarilgunicha chiqqan `order.*` hodisalari bu navbatga
tushmaydi (hisobotdagi taklif).
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Optional

from chat_service.config import RABBITMQ_URL

logger = logging.getLogger(__name__)

EVENTS_EXCHANGE = "logistika.events"

EVENT_ORDER_STATUS_CHANGED = "order.status_changed"
EVENT_ORDER_TRUCK_ASSIGNED = "order.truck_assigned"
EVENT_CHAT_MESSAGE_CREATED = "chat.message_created"

CHAT_ORDER_EVENTS_QUEUE = "chat.order_events"
CHAT_ORDER_EVENTS_PATTERN = "order.*"
CHAT_NOTIFICATIONS_QUEUE = "chat.notifications"
CHAT_NOTIFICATIONS_PATTERN = "chat.*"

PREFETCH = 20

Handler = Callable[[str, dict[str, Any], Optional[datetime]], Awaitable[None]]

_connection: Any = None
_channel: Any = None
_exchange: Any = None
_lock = asyncio.Lock()

# Testlar `publish_event` ni shu ro'yxatga yo'naltiradi (broker'siz).
_capture: Optional[list[tuple[str, dict[str, Any]]]] = None


class QueueUnavailable(RuntimeError):
    pass


def capture_events(target: Optional[list[tuple[str, dict[str, Any]]]]) -> None:
    global _capture
    _capture = target


async def get_channel() -> Any:
    global _connection, _channel, _exchange
    if _channel is not None and not _channel.is_closed:
        return _channel
    async with _lock:
        if _channel is not None and not _channel.is_closed:
            return _channel
        try:
            import aio_pika

            if _connection is None or _connection.is_closed:
                _connection = await _connect()
            _channel = await _connection.channel(publisher_confirms=True)
            await _channel.set_qos(prefetch_count=PREFETCH)
            _exchange = await _declare(_channel)
        except Exception as exc:
            _channel = None
            _exchange = None
            raise QueueUnavailable(f"RabbitMQ'ga ulanib bo'lmadi: {exc}") from exc
        return _channel


async def _connect() -> Any:
    """`connect_robust` ning o'zi, bitta farq bilan: birinchi ulanish muvaffaqiyatsiz
    bo'lsa ulanish obyekti yopiladi. Aks holda aio-pika uni fonda abadiy qayta ulab
    turadi va har qayta urinishimiz (main.py) yana bitta "yetim" ulanish qoldiradi."""
    import aio_pika
    from aio_pika.connection import make_url

    connection = aio_pika.RobustConnection(make_url(RABBITMQ_URL))
    try:
        await connection.connect(timeout=10)
    except Exception:
        await connection.close()
        raise
    return connection


async def _declare(channel: Any) -> Any:
    import aio_pika

    exchange = await channel.declare_exchange(EVENTS_EXCHANGE, aio_pika.ExchangeType.TOPIC, durable=True)
    order_events = await channel.declare_queue(CHAT_ORDER_EVENTS_QUEUE, durable=True)
    await order_events.bind(exchange, CHAT_ORDER_EVENTS_PATTERN)
    notifications = await channel.declare_queue(CHAT_NOTIFICATIONS_QUEUE, durable=True)
    await notifications.bind(exchange, CHAT_NOTIFICATIONS_PATTERN)
    return exchange


def build_event(event: str, payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "event": event,
        "event_id": str(uuid.uuid4()),
        "occurred_at": datetime.now(timezone.utc).isoformat(),
        "data": payload,
    }


async def publish_event(event: str, payload: dict[str, Any]) -> bool:
    """Fire-and-forget: xabar allaqachon bazada, broker o'chgani 500 sabab emas."""
    if _capture is not None:
        _capture.append((event, payload))
        return True
    envelope = build_event(event, payload)
    try:
        import aio_pika

        await get_channel()
        if _exchange is None:
            raise QueueUnavailable("events exchange e'lon qilinmagan")
        await _exchange.publish(
            aio_pika.Message(
                body=json.dumps(envelope, separators=(",", ":"), default=str).encode(),
                content_type="application/json",
                delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
                message_id=envelope["event_id"],
                type=event,
            ),
            routing_key=event,
        )
        return True
    except Exception:
        logger.exception("Hodisa yuborilmadi: %s", event)
        return False


def parse_envelope(body: bytes) -> tuple[str, dict[str, Any], Optional[datetime]]:
    envelope = json.loads(body)
    event = str(envelope["event"])
    data = envelope.get("data") or {}
    occurred_at: Optional[datetime] = None
    raw = envelope.get("occurred_at")
    if raw:
        try:
            occurred_at = datetime.fromisoformat(str(raw))
        except ValueError:
            occurred_at = None
    return event, data, occurred_at


async def consume_order_events(handler: Handler) -> str:
    """`chat.order_events` ni tinglaydi. Xato — `requeue=False` (support kabi):
    buzilgan xabar navbatni cheksiz aylantirmasin, xatoning o'zi logda."""

    async def _on_message(message: Any) -> None:
        async with message.process(requeue=False):
            try:
                event, data, occurred_at = parse_envelope(message.body)
            except (ValueError, KeyError, TypeError):
                logger.exception("Yaroqsiz hodisa tashlandi: %r", message.body[:200])
                return
            try:
                await handler(event, data, occurred_at)
            except Exception:
                logger.exception("Hodisani qayta ishlashda xato: %s", event)

    channel = await get_channel()
    queue = await channel.get_queue(CHAT_ORDER_EVENTS_QUEUE)
    tag = await queue.consume(_on_message)
    logger.info("Buyurtma hodisalari tinglanmoqda: '%s'", CHAT_ORDER_EVENTS_QUEUE)
    return tag


async def cancel_consumer(tag: str) -> None:
    channel = await get_channel()
    queue = await channel.get_queue(CHAT_ORDER_EVENTS_QUEUE)
    await queue.cancel(tag)


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
