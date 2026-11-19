"""RabbitMQ consumer: haydovchi qidirish vazifalarini bajaradigan fon jarayoni.

Ishga tushirish:  `python -m workers.dispatch_worker`
(docker-compose'dagi `dispatch-worker` xizmati aynan shuni bajaradi.)

Nima qiladi:

1. `dispatch.jobs` navbatini o'qiydi va har bir xabar uchun
   `services.dispatch.run_dispatch_job()` ni chaqiradi — ya'ni buyurtmaga keyingi
   nomzodni topib, unga Telegram taklifini yuboradi yoki nomzod qolmagan bo'lsa
   senderga narx oshirishni taklif qiladi.
2. `prefetch_count = DISPATCH_PREFETCH` — bir vaqtning o'zida shuncha buyurtma
   qayta ishlanadi, qolganlari navbatda kutadi. Buyurtmalar ko'payib ketganda
   ham yuk bir tekis taqsimlanadi, hammasi birdaniga qidirilib ketmaydi.
3. Davriy sweep: muddati o'tgan takliflarni yopadi, yo'lga chiqish vaqti kelgan
   rejalashtirilgan buyurtmalarni faollashtiradi va navbatga tushmay qolgan
   buyurtmalarni qaytaradi (ilgari bu FastAPI jarayonida edi — endi web sof API).

Xatolik bo'lganda xabar `requeue=True` bilan QAYTARILMAYDI: bu darhol qayta
yetkazilib issiq siklga aylanardi. O'rniga xabar `dispatch.delayed` navbatiga
qo'yiladi (TTL ~1 daqiqa) va `MAX_RETRIES` marta qayta uriniladi; undan keyin
tekshirish uchun `dispatch.dead` navbatida qoldiriladi.
"""

from __future__ import annotations

import asyncio
import json
import logging
import signal
from typing import Optional

from aio_pika.abc import AbstractIncomingMessage
from sqlalchemy.orm import configure_mappers

# Mapper'lar satr nomlari bilan bog'langan — ishlatishdan oldin BARCHA model moduli
# import qilingan bo'lishi shart (config/main.py va tests/conftest.py dagi kabi).
import Admin_panel.models  # noqa: F401
import driver.models  # noqa: F401
import order.dispatch_models  # noqa: F401
import order.models  # noqa: F401
import users.models  # noqa: F401

configure_mappers()

from config.config import DISPATCH_PREFETCH, async_session  # noqa: E402
from services import dispatch as dispatch_service  # noqa: E402
from services import live_location, live_location_sync, location_watch, outbox, queue, start_reminders  # noqa: E402

logger = logging.getLogger("dispatch_worker")

SWEEP_INTERVAL_SEC = 20
MAX_RETRIES = 3


async def _handle_message(message: AbstractIncomingMessage) -> None:
    """Bitta vazifani bajaradi; xato bo'lsa qayta urinish/dead-letter'ni hal qiladi."""
    # `requeue=False`: xato bo'lsa xabar tashlanadi va qayta urinishni quyida biz
    # o'zimiz boshqaramiz (kechikish bilan), broker cheksiz qaytarmaydi.
    async with message.process(requeue=False):
        try:
            payload = json.loads(message.body)
            order_id = int(payload["order_id"])
        except (ValueError, KeyError, TypeError):
            logger.exception("Yaroqsiz xabar tashlab yuborildi: %r", message.body[:200])
            return

        reason = str(payload.get("reason", "job"))
        attempt = int(payload.get("attempt", 0))

        try:
            async with async_session() as db:
                await dispatch_service.run_dispatch_job(db, order_id, reason)
        except Exception:
            logger.exception(
                "Qidiruv vazifasi bajarilmadi (order #%s, sabab: %s, urinish: %s)",
                order_id,
                reason,
                attempt,
            )
            await _retry_or_park(order_id, reason, attempt)


async def _retry_or_park(order_id: int, reason: str, attempt: int) -> None:
    """Xato bo'lgan vazifani kechikish bilan qaytaradi yoki `dispatch.dead` ga qo'yadi.

    Kechikish `dispatch.delayed` navbatining TTL'i bilan belgilanadi (~1 daqiqa) —
    o'sha vaqtda vaqtinchalik sabab (DB uzilishi, Telegram 5xx) odatda o'tib ketadi.
    """
    try:
        if attempt + 1 < MAX_RETRIES:
            await queue.publish_dispatch_job(order_id, reason, delay=True, attempt=attempt + 1)
        else:
            logger.error(
                "Order #%s uchun qidiruv %s marta muvaffaqiyatsiz — dispatch.dead ga o'tkazildi",
                order_id,
                MAX_RETRIES,
            )
            await queue.publish_dispatch_job(order_id, reason, attempt=attempt, dead_letter=True)
    except queue.QueueUnavailable:
        # Navbat ham ishlamayapti — buyurtma PENDING holatda qoladi va davriy sweep
        # (`requeue_stuck_orders`) uni keyinroq baribir qaytaradi.
        logger.exception("Qayta urinish navbatga qo'yilmadi (order #%s)", order_id)


async def _sweep_loop(stop: asyncio.Event) -> None:
    last_location_sync = 0.0
    while not stop.is_set():
        try:
            async with async_session() as db:
                swept = await dispatch_service.sweep_expired(db)
                if swept:
                    logger.info("Sweep: %s ta muddati o'tgan taklif yopildi", swept)

                promoted = await dispatch_service.promote_due_scheduled(db)
                if promoted:
                    logger.info("Sweep: %s ta rejalashtirilgan buyurtma faollashtirildi", promoted)

                # Yuklash vaqti yaqinlashgan buyurtmalar uchun qidiruv boshlanadi
                # (kelajakka rejalashtirilganlar shu paytgacha kutib turadi).
                started = await dispatch_service.enqueue_due_orders(db)
                if started:
                    logger.info("Sweep: %s ta buyurtma uchun qidiruv boshlandi", started)

                requeued = await dispatch_service.requeue_stuck_orders(db)
                if requeued:
                    logger.info("Sweep: %s ta buyurtma navbatga qaytarildi", requeued)

                # Tracking servisi GPS'ni faqat Redis'ga yozadi — bazaga davriy ko'chirish.
                now_mono = asyncio.get_running_loop().time()
                if now_mono - last_location_sync >= live_location_sync.SYNC_INTERVAL_SEC:
                    last_location_sync = now_mono
                    synced = await live_location_sync.sync_to_db(db)
                    if synced:
                        logger.debug("Sweep: %s ta haydovchi joylashuvi bazaga yozildi", synced)

                # "Start" bosilmagan buyurtmalar: yo'lga chiqish vaqtiga qarab eslatma.
                reminded = await start_reminders.send_due_reminders(db)
                if reminded:
                    logger.info("Sweep: %s ta Start eslatmasi yuborildi", reminded)

                # Faol buyurtmadagi haydovchining GPS'i o'chib qolganini aniqlash.
                warned = await location_watch.check_active_orders(db)
                if warned:
                    logger.info("Sweep: joylashuv bo'yicha %s ta xabar yuborildi", warned)
        except Exception:
            logger.exception("Sweep xatosi")

        try:
            await asyncio.wait_for(stop.wait(), timeout=SWEEP_INTERVAL_SEC)
        except asyncio.TimeoutError:
            pass


OUTBOX_POLL_SEC = 1.0
OUTBOX_PURGE_EVERY_SEC = 3600


async def _outbox_loop(stop: asyncio.Event) -> None:
    """Transactional outbox relay: bazadagi yuborilmagan hodisalarni RabbitMQ'ga.

    Relay core'ning ishi (bazani faqat core biladi), shuning uchun u bildirishnomalar
    servisi emas, shu worker ichida. Batch to'liq bo'lsa kutmasdan davom etadi; broker
    ishlamasa yozuvlar bazada qoladi va keyingi aylanishda qayta urinadi.
    """
    loop = asyncio.get_running_loop()
    last_purge = 0.0
    while not stop.is_set():
        sent = 0
        try:
            async with async_session() as db:
                sent = await outbox.relay_once(db)
                if loop.time() - last_purge > OUTBOX_PURGE_EVERY_SEC:
                    last_purge = loop.time()
                    purged = await outbox.purge_published(db)
                    if purged:
                        logger.info("Outbox: %s ta eski yozuv o'chirildi", purged)
        except Exception:
            logger.exception("Outbox relay xatosi")
        if sent >= outbox.RELAY_BATCH:
            continue
        try:
            await asyncio.wait_for(stop.wait(), timeout=OUTBOX_POLL_SEC)
        except asyncio.TimeoutError:
            pass


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    )

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)

    channel = await queue.get_channel()
    await channel.set_qos(prefetch_count=DISPATCH_PREFETCH)
    jobs_queue = await channel.get_queue(queue.JOBS_QUEUE)

    consumer_tag: Optional[str] = await jobs_queue.consume(_handle_message)
    logger.info(
        "Dispatch worker ishga tushdi: '%s' navbati, prefetch=%s",
        queue.JOBS_QUEUE,
        DISPATCH_PREFETCH,
    )

    sweep_task = asyncio.create_task(_sweep_loop(stop))
    relay_task = asyncio.create_task(_outbox_loop(stop))
    try:
        await stop.wait()
    finally:
        logger.info("To'xtatilmoqda…")
        # Avval yangi xabarlarni qabul qilish to'xtatiladi, so'ng ochiq vazifalar
        # tugashiga qisqa muhlat beriladi (ular `message.process()` ichida ack qiladi).
        try:
            await jobs_queue.cancel(consumer_tag)
        except Exception:
            logger.exception("Consumer'ni to'xtatishda xato")
        await asyncio.sleep(1)

        for task in (sweep_task, relay_task):
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        await queue.close_queue()
        await live_location.close_redis()
        logger.info("Dispatch worker to'xtadi")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
