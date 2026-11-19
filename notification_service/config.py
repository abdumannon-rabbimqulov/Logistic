"""Notification mikroservizining sozlamalari — asosiy `config/config.py` dan mustaqil.

Bu xizmat bazaga ulanmaydi: unga faqat Telegram tokeni, adminlar ro'yxati,
RabbitMQ manzili va mini-app havolasi kerak.
"""

from __future__ import annotations

import os


def _required(key: str) -> str:
    value = os.getenv(key)
    if not value:
        raise RuntimeError(f"{key} muhit o'zgaruvchisi belgilanishi shart")
    return value


def _int_set(raw: str | None) -> frozenset[int]:
    return frozenset(int(part.strip()) for part in (raw or "").split(",") if part.strip())


# Import paytida emas, ishga tushishda tekshiriladi (`main.py: require_settings`) —
# handlerlar (sof funksiyalar) testlarda tokensiz import qilinadi.
BOT_TOKEN = os.getenv("BOT_TOKEN", "")


def require_settings() -> None:
    _required("BOT_TOKEN")
RABBITMQ_URL = os.getenv("RABBITMQ_URL", "amqp://guest:guest@rabbitmq:5672/")
# Asosiy ilova bilan bir xil o'zgaruvchi (`ADMIN`): vergul bilan ajratilgan Telegram id'lar.
ADMIN_IDS = _int_set(os.getenv("ADMIN"))
# Qo'shimcha xodimlar (masalan menejerlar) — support xabarlarini ham olishsin.
STAFF_NOTIFY_IDS = _int_set(os.getenv("STAFF_NOTIFY_IDS"))
WEBAPP_URL = os.getenv("WEBAPP_URL", "")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
TELEGRAM_API = os.getenv("TELEGRAM_API_URL", "https://api.telegram.org")
