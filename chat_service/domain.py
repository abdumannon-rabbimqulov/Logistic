"""Chat qoidalari — sof funksiyalar (baza, tarmoq, FastAPI'siz).

Hamma qaror shu yerda: kim kira oladi, qachon yozib bo'lmaydi, buyurtma hodisasi
suhbatni qanday o'zgartiradi, kim nimani tahrirlay oladi. Router va iste'molchi
faqat shu funksiyalarni chaqiradi. Foyda: (1) testlar bazasiz, (2) Go'ga
ko'chirishda aynan shu fayl qoidalar spetsifikatsiyasi bo'ladi.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from chat_service.models import Conversation, Message

# --- Konstantalar (DB'da satr sifatida saqlanadi) ----------------------------

STATUS_OPEN = "open"
STATUS_READONLY = "readonly"

KIND_TEXT = "text"
KIND_PHOTO = "photo"
KIND_VIDEO = "video"
KIND_VOICE = "voice"
KIND_DOCUMENT = "document"
KIND_LOCATION = "location"

MESSAGE_KINDS = frozenset({KIND_TEXT, KIND_PHOTO, KIND_VIDEO, KIND_VOICE, KIND_DOCUMENT, KIND_LOCATION})
MEDIA_KINDS = frozenset({KIND_PHOTO, KIND_VIDEO, KIND_VOICE, KIND_DOCUMENT})
# Izoh (caption) qo'yish va keyin tahrirlash mumkin bo'lgan turlar.
CAPTION_KINDS = frozenset({KIND_PHOTO, KIND_VIDEO, KIND_DOCUMENT})

ROLE_SENDER = "sender"
ROLE_DRIVER = "driver"

# Core'dagi `OrderStatus` qiymatlari (order/models.py) — katta harf bilan keladi.
ORDER_OPENING_STATUSES = frozenset({"ACCEPTED", "IN_PROGRESS"})
ORDER_TERMINAL_STATUSES = frozenset({"COMPLETED", "CANCELLED"})
# Haydovchi yechib olinadigan holatlar (bekor qilib, qayta qidiruvga tushganda).
ORDER_UNASSIGNED_STATUSES = frozenset({"PENDING"})

EVENT_ORDER_STATUS_CHANGED = "order.status_changed"
EVENT_ORDER_TRUCK_ASSIGNED = "order.truck_assigned"


def as_utc(dt: Optional[datetime]) -> Optional[datetime]:
    """SQLite vaqt zonasini saqlamaydi — naive qiymatni UTC deb qabul qilamiz."""
    if dt is None:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


# --- Kirish va holat --------------------------------------------------------


def role_of(conv: Conversation, user_id: int) -> Optional[str]:
    if user_id == conv.sender_user_id:
        return ROLE_SENDER
    if conv.driver_user_id is not None and user_id == conv.driver_user_id:
        return ROLE_DRIVER
    return None


def is_participant(conv: Conversation, user_id: int) -> bool:
    return role_of(conv, user_id) is not None


def peer_user_id(conv: Conversation, user_id: int) -> Optional[int]:
    role = role_of(conv, user_id)
    if role == ROLE_SENDER:
        return conv.driver_user_id
    if role == ROLE_DRIVER:
        return conv.sender_user_id
    return None


def effective_status(conv: Conversation, now: datetime) -> str:
    """`open` / `readonly`. `readonly_at` o'tgan bo'lsa — DB'da hali `open` bo'lsa ham."""
    if conv.status == STATUS_READONLY:
        return STATUS_READONLY
    readonly_at = as_utc(conv.readonly_at)
    if readonly_at is not None and now >= readonly_at:
        return STATUS_READONLY
    return STATUS_OPEN


def write_block_reason(conv: Conversation, now: datetime) -> Optional[str]:
    """Yozib bo'lmasa — foydalanuvchiga ko'rsatiladigan sabab, bo'lsa `None`."""
    if effective_status(conv, now) == STATUS_READONLY:
        return "Chat yopilgan: buyurtma yakunlanganiga 24 soatdan oshdi"
    if conv.driver_id is None:
        return "Buyurtmada hozir haydovchi yo'q — chat vaqtincha yopiq"
    return None


def can_edit(msg: Message, user_id: int, now: datetime, window_s: int) -> Optional[str]:
    """Tahrirlab bo'lmasa sabab, bo'lsa `None`."""
    if msg.sender_user_id != user_id:
        return "Faqat o'z xabaringizni tahrirlash mumkin"
    if msg.deleted_at is not None:
        return "Xabar o'chirilgan"
    if msg.kind != KIND_TEXT and msg.kind not in CAPTION_KINDS:
        return "Bu turdagi xabarni tahrirlab bo'lmaydi"
    created = as_utc(msg.created_at)
    if created is not None and now - created > timedelta(seconds=window_s):
        return "Tahrirlash muddati o'tgan (48 soat)"
    return None


def can_delete(msg: Message, user_id: int) -> Optional[str]:
    if msg.sender_user_id != user_id:
        return "Faqat o'z xabaringizni o'chirish mumkin"
    if msg.deleted_at is not None:
        return "Xabar allaqachon o'chirilgan"
    return None


def preview_text(kind: str, text: Optional[str], limit: int = 120) -> str:
    """Bildirishnoma va ro'yxat uchun qisqa ko'rinish."""
    labels = {
        KIND_PHOTO: "📷 Rasm",
        KIND_VIDEO: "🎬 Video",
        KIND_VOICE: "🎤 Ovozli xabar",
        KIND_DOCUMENT: "📄 Hujjat",
        KIND_LOCATION: "📍 Joylashuv",
    }
    body = (text or "").strip()
    if kind == KIND_TEXT:
        return body[:limit]
    label = labels.get(kind, kind)
    return f"{label}: {body[:limit]}" if body else label


# --- Buyurtma hodisalari ------------------------------------------------------


@dataclass(frozen=True)
class OrderEvent:
    event: str
    order_id: int
    occurred_at: datetime
    customer_id: Optional[int] = None
    driver_id: Optional[int] = None
    driver_user_id: Optional[int] = None
    new_status: Optional[str] = None


def _int_or_none(value: Any) -> Optional[int]:
    try:
        return int(value) if value is not None and value != "" else None
    except (TypeError, ValueError):
        return None


def parse_order_event(
    event: str, data: dict[str, Any], occurred_at: Optional[datetime] = None
) -> Optional[OrderEvent]:
    """Konvertdan kerakli maydonlarni ajratadi; tushunarsiz hodisa — `None`.

    Payload shartnomasi: `order/crud.py update_order_status` va
    `manager/router.py assign_truck`. `driver_user_id` hozircha core'da YO'Q —
    qo'shilsa avtomatik ishlatiladi (hisobotdagi taklif).
    """
    if event not in (EVENT_ORDER_STATUS_CHANGED, EVENT_ORDER_TRUCK_ASSIGNED):
        return None
    order_id = _int_or_none(data.get("order_id"))
    if order_id is None:
        return None
    status = data.get("new_status")
    return OrderEvent(
        event=event,
        order_id=order_id,
        occurred_at=as_utc(occurred_at) or datetime.now(timezone.utc),
        customer_id=_int_or_none(data.get("customer_id")),
        driver_id=_int_or_none(data.get("driver_id")),
        driver_user_id=_int_or_none(data.get("driver_user_id")),
        new_status=str(status).upper() if status else None,
    )


def apply_order_event(
    conv: Optional[Conversation], ev: OrderEvent, *, readonly_after_s: int
) -> Optional[Conversation]:
    """Hodisani suhbatga qo'llaydi. Yangi/o'zgargan suhbat yoki `None` (hech narsa).

    Qoidalar:
      * ACCEPTED / IN_PROGRESS yoki `truck_assigned` — suhbat ochiladi (yo'q bo'lsa
        yaratiladi), haydovchi yangilanadi, `readonly_at` olib tashlanadi;
      * COMPLETED / CANCELLED — `readonly_at = hodisa vaqti + 24 soat`;
      * PENDING — haydovchi yechildi: eski haydovchi chatga kira olmaydi;
      * hodisa suhbatdagi oxirgi qo'llanganidan ESKI bo'lsa — e'tiborsiz (navbatda
        tartib buzilishi mumkin, eski ACCEPTED yopilgan chatni ochib yubormasin).
    """
    if conv is not None:
        last = as_utc(conv.last_event_at)
        if last is not None and ev.occurred_at < last:
            return None

    opening = ev.event == EVENT_ORDER_TRUCK_ASSIGNED or ev.new_status in ORDER_OPENING_STATUSES

    if conv is None:
        if not opening or ev.customer_id is None:
            return None
        conv = Conversation(
            order_id=ev.order_id,
            sender_user_id=ev.customer_id,
            status=STATUS_OPEN,
        )

    if ev.customer_id is not None:
        conv.sender_user_id = ev.customer_id

    if opening:
        _set_driver(conv, ev.driver_id, ev.driver_user_id)
        conv.status = STATUS_OPEN
        conv.readonly_at = None
    elif ev.new_status in ORDER_TERMINAL_STATUSES:
        conv.readonly_at = ev.occurred_at + timedelta(seconds=readonly_after_s)
    elif ev.new_status in ORDER_UNASSIGNED_STATUSES:
        conv.driver_id = None
        conv.driver_user_id = None
    elif ev.driver_id is not None:
        # SCHEDULED va h.k.: haydovchi o'zgargan bo'lsa yangilaymiz, chatni ochmaymiz.
        _set_driver(conv, ev.driver_id, ev.driver_user_id)

    if ev.new_status:
        conv.order_status = ev.new_status
    conv.last_event_at = ev.occurred_at
    return conv


def _set_driver(conv: Conversation, driver_id: Optional[int], driver_user_id: Optional[int]) -> None:
    if driver_id is None:
        return
    if conv.driver_id != driver_id:
        # Boshqa haydovchi biriktirildi — eskisining user_id si endi yaroqsiz.
        conv.driver_id = driver_id
        conv.driver_user_id = driver_user_id
    elif driver_user_id is not None:
        conv.driver_user_id = driver_user_id
