"""Support (Yordam) mikroservizi — mustaqil FastAPI ilovasi.

Ishga tushirish (Dockerfile CMD):
    alembic -c support_service/alembic.ini upgrade head
    uvicorn support_service.main:app --host 0.0.0.0 --port 8000

Host'ga port ochilmaydi — tashqaridan faqat nginx `/support/` orqali.

Chegara: bu xizmat asosiy loyihaning kodini ham, bazasini ham ishlatmaydi. Uni
asosiy tizim bilan bog'laydigan narsalar — umumiy `SECRET_KEY` (JWT), RabbitMQ
`logistika.events` exchange'i va foydalanuvchi tokeni bilan core API'ga ikki tor
so'rov (`core_client.py`: faollik va buyurtma egaligi).

Hodisa iste'molchisi shu jarayonning ichida, `lifespan` da ishlaydi.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI

from support_service import core_client, crud, kv, queue, realtime, schemas
from support_service.config import LOG_LEVEL
from support_service.db import async_session, engine
from support_service.router import router as support_router

logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
)
logger = logging.getLogger("support_service")

# Kalitlar — `order.models.OrderStatus` QIYMATLARI (katta harf). Ilgari kichik
# harfli kalitlar bo'lgani uchun yorliq hech qachon topilmasdi va foydalanuvchi
# "PENDING → ACCEPTED" kabi xom qiymatni ko'rardi.
_STATUS_LABEL = {
    "SCHEDULED": "rejalashtirilgan",
    "PENDING": "haydovchi qidirilmoqda",
    "ACCEPTED": "haydovchi biriktirildi",
    "IN_PROGRESS": "yo'lda",
    "COMPLETED": "yakunlandi",
    "CANCELLED": "bekor qilindi",
}

_ROLE_LABEL = {
    "sender": "mijoz",
    "driver": "haydovchi",
    "admin": "admin",
    "manager": "menejer",
    "system": "tizim",
}


def status_label(value: Any) -> str:
    raw = str(value or "")
    # `OrderStatus.PENDING` ko'rinishida kelsa ham (str(enum)) — oxirgi qism.
    key = raw.rsplit(".", 1)[-1].upper()
    return _STATUS_LABEL.get(key, raw)


def order_event_text(event: str, data: dict[str, Any]) -> str | None:
    order_id = data.get("order_id")
    if event == queue.EVENT_ORDER_STATUS_CHANGED:
        old, new = data.get("old_status"), data.get("new_status")
        if not new or status_label(old) == status_label(new):
            return None  # holat aslida o'zgarmagan — izoh shovqin bo'lardi
        body = (
            f"Buyurtma #{order_id} holati o'zgardi: {status_label(old)} → {status_label(new)}"
            if old
            else f"Buyurtma #{order_id} holati: {status_label(new)}"
        )
        actor = data.get("changed_by_role")
        if actor:
            body += f" ({_ROLE_LABEL.get(str(actor).lower(), actor)})"
        return body
    if event == queue.EVENT_ORDER_TRUCK_ASSIGNED:
        truck = data.get("truck_number")
        return f"Buyurtma #{order_id} ga yuk mashinasi biriktirildi" + (f": {truck}" if truck else "")
    # Qolgan `order.*` hodisalari (`order.waypoint_changed`, `order.trip_started`, ...)
    # ATAYLAB e'tiborsiz: ular tez-tez chiqadi va murojaatni shovqinga to'ldirardi.
    return None


async def _handle_order_event(event: str, data: dict[str, Any]) -> None:
    """Buyurtma hodisasini shu buyurtmaga oid ochiq murojaatlarga izoh qilib qo'shadi.

    Murojaat faqat buyurtmaga kirish huquqi bor foydalanuvchi tomonidan ochilishi
    mumkin (`router.create_ticket` core'da tekshiradi), shuning uchun izohlar
    begona odamga ketmaydi.
    """
    order_id = data.get("order_id")
    if not order_id:
        return
    body = order_event_text(event, data)
    if body is None:
        return

    async with async_session() as db:
        tickets = await crud.list_open_tickets_for_order(db, int(order_id))
        added = [
            (ticket, await crud.add_message(db, ticket, body, is_system=True, commit=False))
            for ticket in tickets
        ]
        await db.commit()
        for ticket, message in added:
            await db.refresh(ticket)
            await db.refresh(message, attribute_names=["created_at"])
            await realtime.publish(
                "message.created",
                {
                    "ticket_id": ticket.id,
                    "message": schemas.message_out(message).model_dump(mode="json"),
                    "ticket": schemas.ticket_out(ticket, last_message=message).model_dump(
                        mode="json", exclude={"unread_count", "allowed_statuses"}
                    ),
                },
                user_id=ticket.user_id,
            )
        if tickets:
            logger.info(
                "%s: %s ta murojaatga tizim izohi qo'shildi (order #%s)", event, len(tickets), order_id
            )


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Sxema endi alembic bilan (`support_service/migrations`) — konteyner CMD'si
    # uvicorn'dan oldin `alembic upgrade head` ni bajaradi.
    consumer_tag = None
    try:
        consumer_tag = await queue.consume_order_events(_handle_order_event)
    except queue.QueueUnavailable:
        # Broker hali ko'tarilmagan bo'lsa ham API ishlayversin: murojaat yaratish
        # RabbitMQ'ga bog'liq emas, faqat bildirishnoma kechikadi.
        logger.warning("RabbitMQ hozircha mavjud emas — hodisalar tinglanmayapti")

    yield

    if consumer_tag is not None:
        try:
            channel = await queue.get_channel()
            events_queue = await channel.get_queue(queue.SUPPORT_EVENTS_QUEUE)
            await events_queue.cancel(consumer_tag)
        except Exception:
            logger.exception("Consumer'ni to'xtatishda xato")
    await queue.close_queue()
    await core_client.close_client()
    await realtime.close_broker()
    await kv.close_kv()
    await engine.dispose()


app = FastAPI(
    title="Logistika Support Service",
    version="2.0.0",
    description="Yordam (Support) mikroservizi — murojaatlar, yozishmalar va biriktirmalar",
    lifespan=lifespan,
    # Port host'ga ochilmagani uchun Swagger ham proxy (`/support/`) ostida.
    docs_url="/support/docs",
    redoc_url=None,
    openapi_url="/support/openapi.json",
)

app.include_router(support_router)


@app.get("/health", tags=["Service"], summary="Sog'liq tekshiruvi")
@app.get("/support/health", include_in_schema=False)
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "support"}
