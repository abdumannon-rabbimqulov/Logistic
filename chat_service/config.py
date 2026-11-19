"""Chat mikroservizining sozlamalari.

`support_service/config.py` naqshi: asosiy loyihaning `config/config.py` si
ishlatilmaydi — u BOT_TOKEN, OSRM va h.k. talab qiladi va asosiy bazaga ulanadi.
Bu xizmat esa keyinchalik Go'ga ko'chiriladi, shuning uchun hamma sozlama oddiy
muhit o'zgaruvchilari (Go tomonda ham `os.Getenv` bilan bir xil o'qiladi).

`SECRET_KEY` asosiy ilova bilan BIR XIL bo'lishi shart: JWT shu yerda mahalliy
tekshiriladi.
"""

from __future__ import annotations

import hashlib
import hmac
import os


def _required(key: str) -> str:
    value = os.getenv(key)
    if not value:
        raise RuntimeError(f"{key} muhit o'zgaruvchisi belgilanishi shart")
    return value


CHAT_DB_URL = _required("CHAT_DB_URL")
SECRET_KEY = _required("SECRET_KEY")
ALGORITHM = os.getenv("ALGORITHM", "HS256")
RABBITMQ_URL = os.getenv("RABBITMQ_URL", "amqp://guest:guest@rabbitmq:5672/")
REDIS_URL = os.getenv("CHAT_REDIS_URL", "redis://logistika-redis:6379/3")

# Asosiy ilovaning ichki manzili (compose tarmog'ida). Faqat bitta holatda kerak:
# hodisada haydovchining `user_id` si bo'lmasa, haydovchi chatni ochganda uning
# O'Z tokeni bilan `GET /drivers/me` so'raladi va `drivers.id` solishtiriladi
# (`chat_service/access.py`). Bo'sh bo'lsa bu zaxira yo'l o'chadi.
CORE_API_URL = os.getenv("CORE_API_URL", "http://web:8000").rstrip("/")

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

# --- Media ------------------------------------------------------------------

MEDIA_ROOT = os.getenv("CHAT_MEDIA_ROOT", "/app/uploads/chat")
# Imzolangan havolaning amal qilish muddati (soniya). Havola soat chegarasiga
# yaxlitlanadi (`media_urls.sign`) — bir soat ichida URL o'zgarmaydi va brauzer keshi
# ishlaydi.
MEDIA_URL_TTL_S = int(os.getenv("CHAT_MEDIA_URL_TTL_S", str(6 * 3600)))
# Imzo kaliti alohida berilmasa SECRET_KEY dan HMAC bilan hosil qilinadi — JWT kaliti
# media URL'larida bevosita ishlatilmasin (bir kalitni ikki maqsadda ishlatmaslik).
MEDIA_SIGNING_KEY = os.getenv("CHAT_MEDIA_SIGNING_KEY") or hmac.new(
    SECRET_KEY.encode(), b"chat-media-url", hashlib.sha256
).hexdigest()

# Hajm cheklovlari (bayt). Video — talab bo'yicha 50 MB.
MB = 1024 * 1024
MAX_BYTES = {
    "photo": 10 * MB,
    "video": 50 * MB,
    "voice": 10 * MB,
    "document": 20 * MB,
}
MAX_VOICE_SECONDS = 5 * 60
THUMB_MAX_PX = 360

# --- Chat qoidalari -------------------------------------------------------

# Buyurtma COMPLETED/CANCELLED bo'lgach chat shuncha vaqt yozish uchun ochiq qoladi.
READONLY_AFTER_S = int(os.getenv("CHAT_READONLY_AFTER_S", str(24 * 3600)))
# O'z xabarini tahrirlash muddati (Telegram'dagi kabi 48 soat).
EDIT_WINDOW_S = 48 * 3600
MAX_TEXT_LEN = 4096
PAGE_SIZE_MAX = 100
