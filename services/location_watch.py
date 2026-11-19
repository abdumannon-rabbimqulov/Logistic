"""Faol buyurtmadagi haydovchining joylashuvi o'chib qolsa ogohlantirish.

`workers/dispatch_worker.py` sweep sikli har ~20 s da `check_active_orders()` ni
chaqiradi (keyinchalik tracking-service'ga ko'chadi).

Qoidalar ("Start" bosilgan ACCEPTED va IN_PROGRESS buyurtmalar):
  * Haydovchi ilovasi "GPS o'chdi" deb xabar bergan (`gps_lost`) yoki nuqta
    3 daqiqadan eski → haydovchiga Telegram: "joylashuvni yoqing".
  * 10 daqiqadan eski → admin va menejerlarga Telegram.
  * Joylashuv qaytsa → ogohlantirilganlarga "tiklandi" xabari.
Sender alohida xabar olmaydi: kuzatish sahifasida `GET /orders/{id}/eta` orqali
"joylashuv N daqiqa oldin yangilangan" ogohlantirishini ko'radi.

Takroriy xabarlar `live_location.claim_notice_slot` (Redis SET NX EX) bilan cheklanadi.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from order.models import Order, OrderStatus
from services import live_location, order_eta, order_notices, staff

logger = logging.getLogger(__name__)

DRIVER_WARN_AFTER_SEC = 3 * 60
STAFF_WARN_AFTER_SEC = 10 * 60
# Bir haydovchiga takroriy eslatma oralig'i (yoqmaguncha har 15 daqiqada).
DRIVER_REMIND_EVERY_SEC = 15 * 60
# Xodimlarga bir buyurtma bo'yicha takroriy xabar oralig'i.
STAFF_REMIND_EVERY_SEC = 60 * 60
# "Ogohlantirilgan" belgisi shuncha yashaydi — tiklanish xabari uchun.
WARNED_FLAG_TTL_SEC = 24 * 3600


@dataclass(frozen=True)
class Decision:
    warn_driver: bool = False
    warn_staff: bool = False
    recovered: bool = False


def decide(age_sec: Optional[float], gps_lost: bool, *, was_warned: bool) -> Decision:
    """Sof qaror funksiyasi (testlanadi). `age_sec=None` — nuqta umuman yo'q."""
    lost_for_driver = gps_lost or age_sec is None or age_sec > DRIVER_WARN_AFTER_SEC
    if not lost_for_driver:
        return Decision(recovered=was_warned)
    lost_for_staff = age_sec is None or age_sec > STAFF_WARN_AFTER_SEC
    return Decision(warn_driver=True, warn_staff=lost_for_staff)


def _minutes(age_sec: Optional[float]) -> str:
    return "noma'lum vaqtdan" if age_sec is None else f"{int(age_sec // 60)} daqiqadan"


async def check_active_orders(db: AsyncSession, *, now: Optional[datetime] = None) -> int:
    """Barcha faol buyurtmalarni tekshiradi. Qaytaradi: yuborilgan ogohlantirishlar soni."""
    now = now or datetime.now(timezone.utc)
    result = await db.execute(
        select(Order)
        .options(selectinload(Order.driver), selectinload(Order.waypoints))
        .where(
            Order.status.in_([OrderStatus.ACCEPTED, OrderStatus.IN_PROGRESS]),
            Order.driver_id.is_not(None),
            # Faqat yo'lga chiqqanlar: "Start" bosilmagan (masalan 2 kundan keyingi)
            # buyurtmada haydovchi ilovani ochmagan bo'lishi tabiiy — u uchun
            # `services/start_reminders.py` eslatadi, GPS ogohlantirishi emas.
            (Order.started_at.is_not(None)) | (Order.status == OrderStatus.IN_PROGRESS),
        )
    )
    orders = list(result.scalars().all())
    if not orders:
        return 0

    staff_ids: Optional[set[int]] = None
    sent = 0
    for order in orders:
        driver = order.driver
        if driver is None:
            continue
        fix = await order_eta.latest_driver_fix(driver)
        age = order_eta.fix_age_seconds(fix, now)
        gps_lost = await live_location.get_gps_lost(driver.id)
        warned_key = f"locwatch:warned:{order.id}"
        was_warned = await _flag_exists(warned_key)

        decision = decide(age, gps_lost is not None, was_warned=was_warned)

        if decision.recovered:
            await _clear_flag(warned_key)
            order_notices.enqueue_notice(
                db, order_id=order.id, recipient_ids=[driver.user_id], kind="gps_recovered",
                text=f"✅ Joylashuvingiz tiklandi (#{order.id} buyurtma). Rahmat!",
            )
            if await _flag_exists(f"locwatch:staff_warned:{order.id}"):
                await _clear_flag(f"locwatch:staff_warned:{order.id}")
                staff_ids = staff_ids if staff_ids is not None else await staff.staff_ids(db)
                order_notices.enqueue_notice(
                    db, order_id=order.id, recipient_ids=staff_ids, kind="gps_recovered_staff",
                    text=order_notices.staff_text(
                        "Haydovchi joylashuvi tiklandi", f"Buyurtma #{order.id}, haydovchi #{driver.id}"
                    ),
                )
            sent += 1
            continue

        if decision.warn_driver and await live_location.claim_notice_slot(
            f"locwatch:driver:{order.id}", DRIVER_REMIND_EVERY_SEC
        ):
            await _set_flag(warned_key)
            reason = (gps_lost or {}).get("reason")
            hint = (
                "Telefon sozlamalarida Telegram uchun joylashuv ruxsatini yoqing."
                if reason == "denied"
                else "GPS yoqilganini tekshiring va ilovani oching."
            )
            order_notices.enqueue_notice(
                db, order_id=order.id, recipient_ids=[driver.user_id], kind="gps_lost",
                text=(
                    f"⚠️ #{order.id} buyurtma: joylashuvingiz {_minutes(age)} beri kelmayapti.\n"
                    f"{hint}\nSender yukni kuzatib turibdi."
                ),
            )
            sent += 1

        if decision.warn_staff and await live_location.claim_notice_slot(
            f"locwatch:staff:{order.id}", STAFF_REMIND_EVERY_SEC
        ):
            await _set_flag(f"locwatch:staff_warned:{order.id}")
            staff_ids = staff_ids if staff_ids is not None else await staff.staff_ids(db)
            order_notices.enqueue_notice(
                db, order_id=order.id, recipient_ids=staff_ids, kind="gps_lost_staff",
                text=order_notices.staff_text(
                    "Haydovchi joylashuvi o'chgan",
                    f"Buyurtma #{order.id} ({order.status.value})\n"
                    f"Haydovchi #{driver.id}, {driver.truck_number or '-'}\n"
                    f"Oxirgi joylashuv: {_minutes(age)} oldin",
                ),
            )
            sent += 1

    if sent:
        # Bildirishnomalar outbox orqali (services/order_notices.py) — bitta commit.
        await db.commit()
    return sent


async def _flag_exists(key: str) -> bool:
    try:
        return bool(await live_location.get_redis().exists(key))
    except Exception:
        logger.debug("Redis belgisi o'qilmadi: %s", key, exc_info=True)
        return False


async def _set_flag(key: str) -> None:
    try:
        await live_location.get_redis().set(key, "1", ex=WARNED_FLAG_TTL_SEC)
    except Exception:
        logger.debug("Redis belgisi yozilmadi: %s", key, exc_info=True)


async def _clear_flag(key: str) -> None:
    try:
        await live_location.get_redis().delete(key)
    except Exception:
        logger.debug("Redis belgisi o'chirilmadi: %s", key, exc_info=True)
