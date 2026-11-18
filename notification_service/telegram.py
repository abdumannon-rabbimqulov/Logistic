"""Asinxron Telegram Bot API klienti (httpx).

Asosiy ilovadagi `services/notifications.py` sinxron `urllib` + `asyncio.to_thread`
ishlatardi. Bu yerda bitta umumiy `httpx.AsyncClient` (ulanishlar qayta ishlatiladi)
va Telegram'ning 429 (`retry_after`) javobini hurmat qiladigan qayta urinish bor.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

import httpx

from notification_service import config

logger = logging.getLogger(__name__)

TEXT_LIMIT = 4000
MAX_RETRIES = 3

_client: Optional[httpx.AsyncClient] = None


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(base_url=f"{config.TELEGRAM_API}/bot{config.BOT_TOKEN}", timeout=10)
    return _client


async def close() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


def _truncate(text: str) -> str:
    return text if len(text) <= TEXT_LIMIT else text[: TEXT_LIMIT - 20] + "\n... [qisqartirildi]"


async def send_message(chat_id: int, text: str, reply_markup: Optional[dict] = None) -> bool:
    """Xabar yuboradi. `True` — yuborildi. Istisno tashlamaydi.

    Foydalanuvchi botni bloklagan (403) yoki chat yo'q (400) bo'lsa qayta urinilmaydi.
    """
    payload: dict = {"chat_id": chat_id, "text": _truncate(text), "disable_web_page_preview": True}
    if reply_markup:
        payload["reply_markup"] = reply_markup

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = await _get_client().post("/sendMessage", json=payload)
        except httpx.HTTPError as exc:
            logger.warning("Telegram'ga ulanib bo'lmadi (chat %s, urinish %s): %s", chat_id, attempt, exc)
            await asyncio.sleep(attempt)
            continue

        if resp.status_code == 200:
            return True
        if resp.status_code == 429:
            retry_after = 1
            try:
                retry_after = int(resp.json().get("parameters", {}).get("retry_after", 1))
            except ValueError:
                pass
            await asyncio.sleep(min(retry_after, 30))
            continue
        if resp.status_code >= 500:
            await asyncio.sleep(attempt)
            continue
        logger.info("Telegram xabarni rad etdi (chat %s): %s %s", chat_id, resp.status_code, resp.text[:200])
        return False

    logger.warning("Telegram xabari %s urinishdan keyin ham yuborilmadi (chat %s)", MAX_RETRIES, chat_id)
    return False
