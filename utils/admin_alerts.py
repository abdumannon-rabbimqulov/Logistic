

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Iterable

from config.config import ADMIN_IDS

logger = logging.getLogger(__name__)


def _truncate(text: str, limit: int = 3200) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 20] + "\n... [truncated]"


async def _dispatch(message: str, admin_ids: Iterable[int] | None) -> None:
    """Tayyor matnni har bir adminga yuboradi. Hech qachon exception tashlamaydi."""
    ids = list(admin_ids if admin_ids is not None else ADMIN_IDS)
    if not ids:
        return

    message = _truncate(message, 3500)

    # Yagona async Telegram klienti (services/notifications.py). Ilgari bu yerda
    # alohida sinxron `urllib` + thread nusxasi bor edi.
    from services.notifications import send_telegram_message

    for admin_id in ids:
        try:
            await send_telegram_message(int(admin_id), message)
        except Exception as exc:  # noqa: BLE001 — xabar yuborilmasligi asosiy amalni buzmasin
            logger.warning("Admin alert send failed for %s: %s", admin_id, exc)


async def send_error_to_admins(
    *,
    title: str,
    request_id: str,
    method: str,
    path: str,
    client: str,
    exc_type: str,
    details: str,
    admin_ids: Iterable[int] | None = None,
) -> None:
    """Xatoni adminlarga yuboradi. Hech qachon exception tashlamaydi."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    message = (
        f"🚨 Backend Error Alert\n"
        f"{title}\n\n"
        f"time: {now}\n"
        f"request_id: {request_id}\n"
        f"method: {method}\n"
        f"path: {path}\n"
        f"client: {client}\n"
        f"exc_type: {exc_type}\n\n"
        f"details:\n{details}"
    )
    await _dispatch(message, admin_ids)


async def send_notice_to_admins(
    *,
    title: str,
    details: str,
    admin_ids: Iterable[int] | None = None,
) -> None:
    """Oddiy (xato BO'LMAGAN) bildirishnoma — masalan yangi yordam murojaati.

    Nega alohida: ilgari bunday xabarlar ham `send_error_to_admins` orqali ketardi
    va adminga `🚨 Backend Error Alert` sarlavhasi bilan kelardi — hech narsa
    yiqilmagan bo'lsa ham. Natijada haqiqiy xatolar oddiy bildirishnomalar orasida
    ko'zdan qochardi. Bu yerda `request_id`/`exc_type` kabi debug qatorlari ham yo'q:
    ular faqat xatoni izlashda kerak.
    """
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    await _dispatch(f"💬 {title}\n{now}\n\n{details}", admin_ids)


def format_details_for_alert(exc: Exception, *, max_len: int = 1200) -> str:
    raw = f"{type(exc).__name__}: {exc}"
    if len(raw) <= max_len:
        return raw
    return raw[: max_len - 20] + "... [truncated]"

