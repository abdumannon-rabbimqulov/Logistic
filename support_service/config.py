"""Support mikroservizining sozlamalari.

Bu xizmat ATAYLAB asosiy loyihaning `config/config.py` sidan foydalanmaydi: u
`BOT_TOKEN`, Yandex kaliti, OSRM manzili kabi o'ziga aloqasi yo'q o'nlab
o'zgaruvchini talab qiladi va asosiy bazaga ulanib qo'yadi. Mikroserviz faqat
o'ziga keragini biladi — shuning uchun bu yerda qisqa, mustaqil ro'yxat.

`SECRET_KEY` asosiy ilova bilan BIR XIL bo'lishi shart: token shu yerda tekshiriladi.
Foydalanuvchining faol/bloklanganligi esa asosiy ilovadan (`CORE_API_URL`) qisqa
keshlangan holda so'raladi (`support_service/core_client.py`).
"""

from __future__ import annotations

import os


def _required(key: str) -> str:
    value = os.getenv(key)
    if not value:
        raise RuntimeError(f"{key} muhit o'zgaruvchisi belgilanishi shart")
    return value


def _int(key: str, default: int) -> int:
    raw = os.getenv(key)
    return int(raw) if raw not in (None, "") else default


SUPPORT_DB_URL = _required("SUPPORT_DB_URL")
SECRET_KEY = _required("SECRET_KEY")
ALGORITHM = os.getenv("ALGORITHM", "HS256")
RABBITMQ_URL = os.getenv("RABBITMQ_URL", "amqp://guest:guest@rabbitmq:5672/")

# Redis — WebSocket fan-out (pub/sub), foydalanuvchi holati keshi va rate-limit
# hisoblagichlari uchun. Bo'sh qoldirilsa jarayon ichidagi (bitta nusxa uchun)
# xotira varianti ishlatiladi — lokal sinov va testlar shu rejimda ishlaydi.
REDIS_URL = os.getenv("REDIS_URL", "")

# Asosiy ilova API'si (compose tarmog'ida). Foydalanuvchi holati (`/auth/me`) va
# buyurtma egaligi (`/orders/{id}`) shu yerdan, foydalanuvchining O'Z tokeni bilan
# tekshiriladi — support asosiy bazaga ulanmaydi.
CORE_API_URL = os.getenv("CORE_API_URL", "http://web:8000/api").rstrip("/")
CORE_TIMEOUT_SECONDS = float(os.getenv("CORE_TIMEOUT_SECONDS", "3"))
# Foydalanuvchi holati shuncha soniya keshda turadi: bloklangan foydalanuvchi
# eng ko'pi bilan shuncha vaqt ichida support'dan ham chiqarib yuboriladi.
USER_STATUS_CACHE_SECONDS = _int("USER_STATUS_CACHE_SECONDS", 60)

# Biriktirmalar (rasm/video/hujjat). Lokal volume — `storage.LocalStorage`.
UPLOAD_DIR = os.getenv("SUPPORT_UPLOAD_DIR", "/app/uploads/support")
SIGNED_URL_TTL_SECONDS = _int("SUPPORT_SIGNED_URL_TTL", 3600)
MAX_IMAGE_BYTES = _int("SUPPORT_MAX_IMAGE_BYTES", 10 * 1024 * 1024)
MAX_VIDEO_BYTES = _int("SUPPORT_MAX_VIDEO_BYTES", 50 * 1024 * 1024)
MAX_DOCUMENT_BYTES = _int("SUPPORT_MAX_DOCUMENT_BYTES", 20 * 1024 * 1024)

# Rate-limit: oddiy foydalanuvchi uchun. Xodim bir vaqtda o'nlab murojaatga
# javob beradi — unga alohida, kengroq chegara.
RATE_MESSAGES_PER_MINUTE = _int("SUPPORT_RATE_MESSAGES_PER_MINUTE", 10)
RATE_STAFF_MESSAGES_PER_MINUTE = _int("SUPPORT_RATE_STAFF_MESSAGES_PER_MINUTE", 60)
RATE_TICKETS_PER_HOUR = _int("SUPPORT_RATE_TICKETS_PER_HOUR", 5)

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

# Ichki xodim rollari — murojaatlarning HAMMASINI ko'radi va holatini o'zgartiradi.
STAFF_ROLES = frozenset({"admin", "manager"})
