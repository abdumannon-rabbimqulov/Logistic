"""Chat mikroservizi — buyurtma bo'yicha yuk egasi ↔ haydovchi yozishmasi.

Ishga tushirish (konteynerda migratsiya bilan, `chat_service/Dockerfile`):
    alembic -c chat_service/alembic.ini upgrade head
    uvicorn chat_service.main:app --host 0.0.0.0 --port 8000

Chegara (support_service bilan bir xil): asosiy loyihaning kodi ham, bazasi ham
ishlatilmaydi. Bog'lanish — umumiy `SECRET_KEY` (JWT), RabbitMQ `logistika.events`
(`order.*` ni tinglaydi, `chat.message_created` chiqaradi) va Redis (real vaqt,
o'z DB raqamida). Yagona HTTP bog'liqlik ixtiyoriy: haydovchi `user_id` sini
tasdiqlash (`access.py`).
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from chat_service import queue
from chat_service.config import LOG_LEVEL
from chat_service.db import dispose_engine
from chat_service.events import handle_order_event
from chat_service.realtime import RedisBroadcaster, get_broadcaster
from chat_service.router import router as chat_router
from chat_service.ws import router as ws_router

logging.basicConfig(level=LOG_LEVEL, format="%(asctime)s %(levelname)-8s %(name)s: %(message)s")
logger = logging.getLogger("chat_service")


@asynccontextmanager
async def lifespan(app: FastAPI):
    consumer_tag = None
    try:
        consumer_tag = await queue.consume_order_events(handle_order_event)
    except queue.QueueUnavailable:
        # Broker hali ko'tarilmagan bo'lsa ham API ishlayversin: mavjud chatlar
        # ishlaydi, faqat yangi buyurtmalar uchun chat ochilishi kechikadi.
        logger.warning("RabbitMQ hozircha mavjud emas — buyurtma hodisalari tinglanmayapti")

    yield

    if consumer_tag is not None:
        try:
            await queue.cancel_consumer(consumer_tag)
        except Exception:
            logger.exception("Consumer'ni to'xtatishda xato")
    await queue.close_queue()
    broadcaster = get_broadcaster()
    if isinstance(broadcaster, RedisBroadcaster):
        await broadcaster.close()
    await dispose_engine()


app = FastAPI(
    title="Logistika Chat Service",
    version="1.0.0",
    description="Buyurtma chati — yuk egasi va haydovchi yozishmasi",
    lifespan=lifespan,
)

app.include_router(chat_router)
app.include_router(ws_router)


@app.get("/health", tags=["Service"], summary="Sog'liq tekshiruvi")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "chat"}
