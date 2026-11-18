"""Telegram orqali foydalanuvchilarga xabar yuborish (core ichidan, async httpx).

Buyurtma holati va support bildirishnomalari endi `notification_service` da; bu
modul dispatch takliflari kabi DARHOL javob (message_id) kerak bo'lgan xabarlar uchun.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Literal, Optional

import httpx

DeletedBy = Literal["admin", "sender"]

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config.config import BOT_TOKEN
from driver.models import Driver

logger = logging.getLogger(__name__)


def _truncate(text: str, limit: int = 3200) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 20] + "\n... [truncated]"


def inline_keyboard(buttons: list[list[tuple[str, str]]]) -> dict:
    """[[("✅ Qabul qilish", "dispatch:accept:5")], ...] -> Telegram `reply_markup` dict.

    Ikkinchi element "http://"/"https://" bilan boshlansa — havola tugmasi (url),
    aks holda odatdagi callback tugmasi bo'ladi.
    """

    def _button(text: str, action: str) -> dict:
        key = "url" if action.startswith(("http://", "https://")) else "callback_data"
        return {"text": text, key: action}

    return {"inline_keyboard": [[_button(text, action) for text, action in row] for row in buttons]}


def url_keyboard(buttons: list[list[tuple[str, Optional[str]]]]) -> Optional[dict]:
    """inline_keyboard kabi, lekin URL'i None bo'lgan tugmalarni tashlab ketadi.

    Koordinata bo'lmasa navigatsiya havolasi tuzilmaydi (None qaytadi) — shunda
    tugma umuman ko'rsatilmasligi kerak. Hech narsa qolmasa None qaytariladi.
    """
    rows = [[(text, url) for text, url in row if url] for row in buttons]
    non_empty = [row for row in rows if row]
    if not non_empty:
        return None
    return inline_keyboard(non_empty)  # type: ignore[arg-type]


_client: Optional[httpx.AsyncClient] = None


def _get_client() -> httpx.AsyncClient:
    """Bitta umumiy async klient — ulanishlar qayta ishlatiladi (ilgari har xabarga
    yangi `urllib` ulanishi + alohida thread ochilardi)."""
    global _client
    if _client is None:
        _client = httpx.AsyncClient(base_url=f"https://api.telegram.org/bot{BOT_TOKEN}", timeout=8)
    return _client


async def _call(method: str, payload: dict) -> Optional[dict]:
    """Bot API chaqiruvi. Muvaffaqiyatda `result`, aks holda `None`. 429 da bir marta kutadi."""
    for attempt in range(2):
        resp = await _get_client().post(f"/{method}", json=payload)
        if resp.status_code == 429 and attempt == 0:
            try:
                retry_after = int(resp.json().get("parameters", {}).get("retry_after", 1))
            except ValueError:
                retry_after = 1
            await asyncio.sleep(min(retry_after, 10))
            continue
        if resp.status_code != 200:
            logger.warning("Telegram %s rad etildi: %s %s", method, resp.status_code, resp.text[:200])
            return None
        return resp.json().get("result")
    return None


async def send_telegram_message(
    chat_id: int, text: str, *, reply_markup: Optional[dict] = None
) -> Optional[int]:
    """Bitta Telegram chat_id ga xabar; xato bo'lsa exception tashlamaydi. Xabar id qaytaradi."""
    if not BOT_TOKEN:
        logger.warning("BOT_TOKEN yo'q — Telegram xabari yuborilmadi (chat_id=%s)", chat_id)
        return None
    payload: dict = {"chat_id": int(chat_id), "text": _truncate(text), "disable_web_page_preview": True}
    if reply_markup is not None:
        payload["reply_markup"] = reply_markup
    try:
        result = await _call("sendMessage", payload)
    except (ValueError, httpx.HTTPError) as exc:
        logger.warning("Telegram xabar yuborilmadi (chat_id=%s): %s", chat_id, exc)
        return None
    except Exception as exc:
        logger.warning("Kutilmagan Telegram xato (chat_id=%s): %s", chat_id, exc)
        return None
    return (result or {}).get("message_id")


async def edit_telegram_message(
    chat_id: int, message_id: int, text: str, *, reply_markup: Optional[dict] = None
) -> None:
    """Avval yuborilgan xabarni tahrirlaydi (masalan "⏱ Vaqt tugadi"); xato bo'lsa jim ketadi."""
    if not chat_id or not message_id or not BOT_TOKEN:
        return
    payload = {
        "chat_id": int(chat_id),
        "message_id": int(message_id),
        "text": _truncate(text),
        "disable_web_page_preview": True,
        # reply_markup berilmasa (None) — tugmalar olib tashlanadi (bo'sh inline_keyboard)
        "reply_markup": reply_markup if reply_markup is not None else {"inline_keyboard": []},
    }
    try:
        await _call("editMessageText", payload)
    except (ValueError, httpx.HTTPError) as exc:
        logger.warning("Telegram xabar tahrirlanmadi (chat_id=%s, message_id=%s): %s", chat_id, message_id, exc)
    except Exception as exc:
        logger.warning("Kutilmagan Telegram tahrirlash xatosi (chat_id=%s): %s", chat_id, exc)


def order_deleted_message(cargo_name: str, deleted_by: DeletedBy) -> str:
    if deleted_by == "sender":
        return (
            f"Sizga biriktirilgan '{cargo_name}' buyurtmasi "
            f"mijoz tomonidan bekor qilindi (o'chirildi)."
        )
    return (
        f"Sizga biriktirilgan '{cargo_name}' buyurtmasi admin tomonidan o'chirildi."
    )


async def notify_drivers_order_deleted(
    db: AsyncSession,
    driver_id: int,
    cargo_name: str,
    *,
    deleted_by: DeletedBy = "admin",
) -> None:
    """Buyurtmaga biriktirilgan haydovchiga (Telegram user_id) bekor qilingani haqida xabar yuboradi."""
    result = await db.execute(
        select(Driver.user_id).where(Driver.id == int(driver_id))
    )
    chat_id = result.scalar_one_or_none()
    if chat_id is None:
        return

    message = order_deleted_message(cargo_name, deleted_by)
    await send_telegram_message(int(chat_id), message)
