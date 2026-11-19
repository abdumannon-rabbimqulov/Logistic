"""Buyurtma va nuqta holatlarining o'zbekcha nomlari (backend xabarlari uchun).

Bitta joyda: xato matnlari (`services/order_flow.py`) va boshqa matnlar shundan oladi.
Support mikroservizi o'z nusxasini saqlaydi (core'ni import qilmaydi) — barcha
holatlar qamrab olingani `tests/test_event_contract.py` da tekshiriladi.
"""

from order.models import OrderStatus, WaypointStatus

ORDER_STATUS_LABEL: dict[OrderStatus, str] = {
    OrderStatus.SCHEDULED: "rejalashtirilgan",
    OrderStatus.PENDING: "haydovchi qidirilmoqda",
    OrderStatus.ACCEPTED: "qabul qilingan",
    OrderStatus.IN_PROGRESS: "yo'lda",
    OrderStatus.COMPLETED: "yakunlangan",
    OrderStatus.CANCELLED: "bekor qilingan",
}

# Xato matnida xom enum qiymati ("'PENDING' holatidan 'ARRIVED' holatiga") o'rniga.
WAYPOINT_STATUS_LABEL: dict[WaypointStatus, str] = {
    WaypointStatus.PENDING: "kutilmoqda",
    WaypointStatus.ARRIVED: "yetib keldi",
    WaypointStatus.COMPLETED: "yakunlandi",
    WaypointStatus.SKIPPED: "o'tkazib yuborildi",
}
