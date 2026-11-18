"""Tracking mikroservizi sozlamalari — asosiy `config/config.py` dan mustaqil.

Bazaga ulanmaydi. Avtorizatsiya: WebSocket ochilganda (bir marta) foydalanuvchi
tokeni bilan core API'ga so'rov (`CORE_API_URL`). Joylashuvlar — Redis'da, core bilan
umumiy kalit formati (`services/live_location.py`).
"""

from __future__ import annotations

import os

REDIS_URL = os.getenv(
    "TRACKING_REDIS_URL",
    f"redis://{os.getenv('REDIS_HOST', 'logistika_redis')}:{os.getenv('REDIS_PORT', '6379')}/0",
)
CORE_API_URL = os.getenv("CORE_API_URL", "http://web:8000").rstrip("/")
# Jonli nuqta shuncha yashaydi va shundan eski GPS nuqtasi "jonli" hisoblanmaydi.
LIVE_LOC_TTL_SEC = int(os.getenv("LIVE_LOC_TTL_SEC", "120"))
API_PREFIX = (os.getenv("API_PUBLIC_PREFIX", "/api") or "/api").rstrip("/")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
