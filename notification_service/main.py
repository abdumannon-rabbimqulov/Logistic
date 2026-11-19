"""Notification mikroservizi: hodisalarni oladi va Telegram xabarlarini yuboradi.

Ishga tushirish:  `python -m notification_service.main`

O'qiydigan navbatlar (`logistika.events` topic exchange):
  * `support.notifications`      — `support.*` (murojaatlar)
  * `notifications.order_events` — `order.*`   (buyurtma holati, Start, nuqtalar)

Bazaga ulanmaydi va asosiy kodni import qilmaydi — alohida image (`Dockerfile`).
Xato bo'lgan xabar `requeue=False` bilan tashlanadi: bildirishnoma kritik bo'lmagan
yon ta'sir, cheksiz qayta urinish navbatni tiqib qo'yardi.
"""

from __future__ import annotations

import asyncio
import json
import logging
import signal

import aio_pika
from aio_pika.abc import AbstractIncomingMessage

from contracts import events as c
from notification_service import config, telegram
from notification_service.handlers import route

logger = logging.getLogger("notification_service")

PREFETCH = 10


async def handle_message(message: AbstractIncomingMessage) -> None:
    async with message.process(requeue=False):
        try:
            envelope = json.loads(message.body)
            event = str(envelope["event"])
            data = envelope.get("data") or {}
        except (ValueError, KeyError, TypeError):
            logger.exception("Yaroqsiz hodisa tashlab yuborildi: %r", message.body[:200])
            return

        try:
            outgoing = route(event, data)
        except Exception:
            logger.exception("Hodisani qayta ishlashda xato: %s", event)
            return
        for item in outgoing:
            await telegram.send_message(item.chat_id, item.text, item.reply_markup)


async def main() -> None:
    logging.basicConfig(
        level=config.LOG_LEVEL,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    )
    config.require_settings()
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)

    connection = await aio_pika.connect_robust(config.RABBITMQ_URL)
    channel = await connection.channel()
    await channel.set_qos(prefetch_count=PREFETCH)
    exchange = await channel.declare_exchange(c.EVENTS_EXCHANGE, aio_pika.ExchangeType.TOPIC, durable=True)

    queues = []
    for name, pattern in (
        (c.SUPPORT_NOTIFICATIONS_QUEUE, c.SUPPORT_NOTIFICATIONS_PATTERN),
        (c.ORDER_NOTIFICATIONS_QUEUE, c.ORDER_NOTIFICATIONS_PATTERN),
    ):
        q = await channel.declare_queue(name, durable=True)
        await q.bind(exchange, pattern)
        queues.append((q, await q.consume(handle_message)))
    logger.info("Notification servisi ishga tushdi: %s", ", ".join(q.name for q, _ in queues))

    try:
        await stop.wait()
    finally:
        for q, tag in queues:
            try:
                await q.cancel(tag)
            except Exception:
                logger.exception("Consumer'ni to'xtatishda xato: %s", q.name)
        await telegram.close()
        await connection.close()
        logger.info("Notification servisi to'xtadi")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
