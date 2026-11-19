"""Loglarda maxfiy qiymatlarni yashirish — barcha servislar uchun umumiy.

Muammo: `httpx` har so'rovni INFO darajasida TO'LIQ manzil bilan yozadi
(`HTTP Request: POST https://api.telegram.org/bot<TOKEN>/sendMessage`), uvicorn esa
WebSocket manzilini query bilan (`/ws/dispatch?token=<JWT>`). Natijada Telegram bot
tokeni va foydalanuvchi JWT'lari server loglariga tushib qolardi.

`install()` ikkita ish qiladi (servis `logging.basicConfig` dan keyin chaqiriladi):
  1. `httpx` va `httpcore` loglarini WARNING ga tushiradi — ichki so'rovlar yozilmaydi;
  2. root va uvicorn handler'lariga filtr qo'yadi: log yozuvidagi `token=...`, `sig=...`
     va `bot<id>:<sir>` qiymatlari `***` ga almashtiriladi (boshqa kutubxona manzil
     yozsa ham).

Filtr yozuvning `args` tuzilishini saqlaydi (uvicorn `AccessFormatter` 5 ta argumentni
kutadi), faqat matnli qiymatlarni almashtiradi. Faqat standart kutubxona — shu paket
har servis image'iga ko'chiriladi.
"""

from __future__ import annotations

import logging
import re

_REPLACEMENTS: tuple[tuple[re.Pattern[str], str], ...] = (
    # ?token=..., &access_token=..., sig=... (imzolangan havola)
    (re.compile(r"\b((?:access_|refresh_)?token|sig)=[^&\s\"']+", re.IGNORECASE), r"\1=***"),
    # Telegram: https://api.telegram.org/bot123456789:AAH...secret/sendMessage
    (re.compile(r"\bbot\d{6,}:[A-Za-z0-9_-]{20,}"), "bot***"),
)

_NOISY_LOGGERS = ("httpx", "httpcore")
_HANDLER_LOGGERS = ("", "uvicorn", "uvicorn.error", "uvicorn.access")


def redact(text: str) -> str:
    for pattern, replacement in _REPLACEMENTS:
        text = pattern.sub(replacement, text)
    return text


class RedactFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = redact(record.msg)
        if isinstance(record.args, tuple):
            record.args = tuple(redact(a) if isinstance(a, str) else a for a in record.args)
        return True


def install() -> None:
    """Idempotent: qayta chaqirilsa filtr ikki marta qo'shilmaydi."""
    for name in _NOISY_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)
    handlers = {h for name in _HANDLER_LOGGERS for h in logging.getLogger(name).handlers}
    for handler in handlers:
        if not any(isinstance(f, RedactFilter) for f in handler.filters):
            handler.addFilter(RedactFilter())
