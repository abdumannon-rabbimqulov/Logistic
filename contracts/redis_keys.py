"""Redis kalitlari va kanallari (core + tracking_service): jonli joylashuv va dispatch signallari."""

from __future__ import annotations

# Oxirgi nuqta (JSON), TTL = LIVE_LOC_TTL_SEC.
DRIVER_LOCATION_PREFIX = "driver_location:"
DRIVER_LOCATION_PATTERN = DRIVER_LOCATION_PREFIX + "*"
# Haydovchi ilovasi "GPS o'chdi" degan belgi.
DRIVER_GPS_LOST_PREFIX = "driver_gps_lost:"
# Barcha yangilanishlar (admin xaritasi).
DRIVER_LOCATIONS_CHANNEL = "driver_locations_channel"
# Faqat bitta haydovchi (sender kuzatuvi).
DRIVER_LOCATION_CHANNEL_PREFIX = "driver_location_ch:"


def driver_location_key(driver_id: int) -> str:
    return f"{DRIVER_LOCATION_PREFIX}{driver_id}"


def driver_gps_lost_key(driver_id: int) -> str:
    return f"{DRIVER_GPS_LOST_PREFIX}{driver_id}"


def driver_location_channel(driver_id: int) -> str:
    return f"{DRIVER_LOCATION_CHANNEL_PREFIX}{driver_id}"


# Haydovchiga "taklifingiz o'zgardi" signali: core (services/dispatch_signal.py) →
# tracking_service WS `/drivers/ws/dispatch` → haydovchi ilovasi. Xabar faqat signal
# (`{"event": "dispatch_changed"}`) — ilova taklifning o'zini `GET /orders/dispatch/active`
# dan oladi, shuning uchun ruxsat va serializatsiya bitta joyda (core'da) qoladi.
DRIVER_DISPATCH_CHANNEL_PREFIX = "driver_dispatch_ch:"
DISPATCH_CHANGED_EVENT = "dispatch_changed"


def driver_dispatch_channel(driver_id: int) -> str:
    return f"{DRIVER_DISPATCH_CHANNEL_PREFIX}{driver_id}"


# Buyurtma sahifasi (sender/haydovchi kuzatuvi) uchun "buyurtma o'zgardi" signali:
# core (outbox relay va dispatch: services/order_signal.py) → tracking_service WS
# `/orders/{id}/ws/updates` → brauzer. Faqat signal (`{"event": "order_changed"}`);
# buyurtmaning o'zi `GET /orders/{id}` dan olinadi — ruxsat va serializatsiya core'da qoladi.
ORDER_UPDATES_CHANNEL_PREFIX = "order_updates_ch:"
ORDER_CHANGED_EVENT = "order_changed"


def order_updates_channel(order_id: int) -> str:
    return f"{ORDER_UPDATES_CHANNEL_PREFIX}{order_id}"
