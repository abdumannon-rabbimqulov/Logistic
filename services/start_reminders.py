""""Start" eslatmalari — haydovchi o'z vaqtida yo'lga chiqishi uchun.

Haydovchi buyurtmani qabul qilganda `departure_at` hisoblanadi: yuklash vaqtidan
(`pickup_at`) haydovchining yuk olish nuqtasigacha yo'l vaqti ayriladi
(`services/dispatch.py: resolve_departure_plan`). Masalan mijoz yukni 2 kundan keyin
ortishni belgilagan va haydovchi 300 km uzoqda bo'lsa — u ~4 soat oldin chiqishi kerak.

`workers/dispatch_worker.py` sweep sikli har ~20 s da `send_due_reminders()` ni
chaqiradi. "Start" bosilmagan har bir buyurtma uchun (vaqt `departure_at` ga nisbatan):

    1 kun qolganda    → "Ertaga yo'lga chiqasiz"
    2 soat qolganda   → "2 soatdan keyin"
    30 daqiqa qolganda→ "30 daqiqadan keyin, Start bosishni unutmang"
    vaqti keldi       → "Hozir yo'lga chiqing — Start bosing", keyin har 15 daqiqada
    30 daqiqa kechiksa→ admin va menejerlarga xabar (bir marta)

Har bosqich bir marta yuboriladi (`live_location.claim_notice_slot`).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from config.config import APP_TIMEZONE
from order.models import Order, OrderStatus
from services import live_location, notifications, staff
from utils.admin_alerts import send_notice_to_admins

logger = logging.getLogger(__name__)

LATE_REPEAT = timedelta(minutes=15)
STAFF_LATE_AFTER = timedelta(minutes=30)
SLOT_TTL_SEC = 3 * 24 * 3600


@dataclass(frozen=True)
class Reminder:
    key: str  # takrorlanmaslik kaliti (buyurtma ichida)
    text: str
    notify_staff: bool = False


def _fmt_time(dt: datetime) -> str:
    try:
        from zoneinfo import ZoneInfo

        dt = dt.astimezone(ZoneInfo(APP_TIMEZONE))
    except Exception:
        pass
    return dt.strftime("%d.%m %H:%M")


def reminder_for(order_id: int, departure_at: datetime, now: datetime) -> Optional[Reminder]:
    """Hozir yuborilishi kerak bo'lgan eslatma (sof funksiya, testlanadi).

    Faqat JORIY bosqich qaytariladi: haydovchi buyurtmani 3 soat oldin qabul qilgan
    bo'lsa, "1 kun qoldi" eslatmasi kechikib yuborilmaydi.
    """
    left = departure_at - now
    when = _fmt_time(departure_at)
    head = f"#{order_id} buyurtma"

    if left > timedelta(hours=24):
        return None
    if left > timedelta(hours=2):
        return Reminder("d1", f"📅 {head}: yo'lga chiqish vaqti — {when}. Yuk olish joyiga o'z vaqtida yetib boring.")
    if left > timedelta(minutes=30):
        return Reminder("h2", f"⏰ {head}: 2 soatdan kam qoldi, {when} da yo'lga chiqishingiz kerak.")
    if left > timedelta(0):
        return Reminder(
            "m30",
            f"⏰ {head}: {when} da yo'lga chiqasiz. Chiqayotganda ilovada \"Start\" tugmasini bosing.",
        )

    late = -left
    slot = int(late / LATE_REPEAT)
    text = (
        f"🚨 {head}: yo'lga chiqish vaqti keldi ({when}). Hoziroq yo'lga chiqing va "
        "ilovada \"Start\" tugmasini bosing — mijoz sizni kutmoqda."
    )
    if slot > 0:
        text = (
            f"🚨 {head}: {int(late.total_seconds() // 60)} daqiqa kechikyapsiz. "
            "Yo'lga chiqqan bo'lsangiz ilovada \"Start\" ni bosing."
        )
    return Reminder(f"late{slot}", text, notify_staff=late >= STAFF_LATE_AFTER)


async def send_due_reminders(db: AsyncSession, *, now: Optional[datetime] = None) -> int:
    """Start bosilmagan buyurtmalar bo'yicha eslatmalar. Qaytaradi: yuborilganlar soni."""
    now = now or datetime.now(timezone.utc)
    result = await db.execute(
        select(Order)
        .options(selectinload(Order.driver))
        .where(
            Order.status.in_([OrderStatus.SCHEDULED, OrderStatus.ACCEPTED]),
            Order.driver_id.is_not(None),
            Order.started_at.is_(None),
        )
    )
    sent = 0
    staff_ids: Optional[set[int]] = None
    for order in result.scalars().all():
        if order.driver is None:
            continue
        departure_at = order.departure_at or order.pickup_at
        if departure_at is None:
            continue
        if departure_at.tzinfo is None:
            departure_at = departure_at.replace(tzinfo=timezone.utc)

        reminder = reminder_for(order.id, departure_at, now)
        if reminder is None:
            continue
        if await live_location.claim_notice_slot(f"start_remind:{order.id}:{reminder.key}", SLOT_TTL_SEC):
            await notifications.send_telegram_message(order.driver.user_id, reminder.text)
            sent += 1

        if reminder.notify_staff and await live_location.claim_notice_slot(
            f"start_remind:{order.id}:staff", SLOT_TTL_SEC
        ):
            staff_ids = staff_ids if staff_ids is not None else await staff.staff_ids(db)
            await send_notice_to_admins(
                title="Haydovchi yo'lga chiqmadi",
                details=(
                    f"Buyurtma #{order.id}: yo'lga chiqish vaqti {_fmt_time(departure_at)} edi, "
                    f"haydovchi #{order.driver.id} ({order.driver.truck_number or '-'}) hali \"Start\" bosmagan."
                ),
                admin_ids=staff_ids,
            )
            sent += 1
    return sent
