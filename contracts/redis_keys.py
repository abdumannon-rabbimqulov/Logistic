"""Jonli joylashuv uchun Redis kalitlari va kanallari (core + tracking_service)."""

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
