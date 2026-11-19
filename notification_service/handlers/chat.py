"""Chat xabarlari (`chat.message_created`) → qabul qiluvchiga Telegram bildirishnomasi.

Boshqa handlerlardan farqi — HOLATLI: bir daqiqa ichidagi xabarlar birlashtiriladi.
Har `qabul qiluvchi × buyurtma` jufti uchun:

    1-xabar                → darhol "💬 Yangi xabar: <matn>" va 60 s oyna ochiladi
    oyna ichidagi xabarlar → faqat sanaladi
    oyna tugaganda         → hisob > 0 bo'lsa bitta "yana N ta yangi xabar", yangi oyna

Ya'ni haydovchi ketma-ket 10 ta xabar yozsa sender'ga 2 ta bildirishnoma boradi.

Holat jarayon XOTIRASIDA: bu xizmat bazaga ham, Redis'ga ham ulanmaydi va bitta
nusxada ishlaydi. Qayta ishga tushganda oynalar yo'qoladi — keyingi xabar shunchaki
yangi oyna ochadi (bildirishnoma uchun maqbul). Bir nechta replika kerak bo'lsa,
holatni Redis'ga ko'chirish kerak bo'ladi.

Qabul qiluvchi chatni ochib turgan bo'lsa (`recipient_online`) — bildirishnoma yo'q.
`recipient_user_id` bo'lmasa (haydovchi hali bir marta ham chatni ochmagan va core
hodisasida `driver_user_id` yo'q) — bu xizmat bazasiz uni topa olmaydi, xabar o'tkaziladi.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Optional

from notification_service import config
from notification_service.messages import Outgoing

logger = logging.getLogger(__name__)

WINDOW_S = 60

_ROLE_LABEL = {"driver": "Haydovchi", "sender": "Yuk egasi"}


def chat_button(order_id: int) -> Optional[dict]:
    """"Chatni ochish" tugmasi (lokal http muhitda — tugmasiz)."""
    text = "💬 Chatni ochish"
    link = (config.TELEGRAM_MINIAPP_LINK or "").rstrip("/")
    if link:
        return {"inline_keyboard": [[{"text": text, "url": f"{link}?startapp=chat_{order_id}"}]]}
    base = (config.WEBAPP_URL or "").rstrip("/")
    if base.startswith("https://"):
        return {"inline_keyboard": [[{"text": text, "web_app": {"url": f"{base}/orders/{order_id}/chat"}}]]}
    return None


def first_message(recipient: int, order_id: int, data: dict[str, Any]) -> Outgoing:
    who = _ROLE_LABEL.get(str(data.get("sender_role")), "Yangi xabar")
    preview = str(data.get("preview") or "").strip()[:300]
    text = f"💬 Buyurtma #{order_id} — yangi xabar"
    if preview:
        text += f"\n{who}: {preview}"
    return Outgoing(recipient, text, chat_button(order_id))


def digest_message(recipient: int, order_id: int, count: int) -> Outgoing:
    return Outgoing(
        recipient, f"📨 Buyurtma #{order_id} chatida yana {count} ta yangi xabar", chat_button(order_id)
    )


@dataclass
class _Window:
    until: float
    pending: int = 0
    task: Optional[asyncio.Task] = None


SendFn = Callable[[Outgoing], Awaitable[Any]]


class ChatCoalescer:
    def __init__(
        self,
        send: SendFn,
        *,
        window_s: float = WINDOW_S,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.send = send
        self.window_s = window_s
        self.clock = clock
        self.sleep = sleep
        self.windows: dict[tuple[int, int], _Window] = {}

    async def handle(self, data: dict[str, Any]) -> None:
        try:
            order_id = int(data["order_id"])
        except (KeyError, TypeError, ValueError):
            logger.warning("chat.message_created: order_id yo'q — tashlandi")
            return
        recipient = data.get("recipient_user_id")
        if recipient is None:
            logger.info("Chat #%s: qabul qiluvchining user_id si noma'lum — bildirishnomasiz", order_id)
            return
        if data.get("recipient_online"):
            return
        recipient = int(recipient)

        key = (recipient, order_id)
        now = self.clock()
        window = self.windows.get(key)
        if window is None or (now >= window.until and window.task is None):
            self.windows[key] = _Window(until=now + self.window_s)
            await self.send(first_message(recipient, order_id, data))
            return

        window.pending += 1
        if window.task is None:
            window.task = asyncio.create_task(self._flush(key, order_id))

    async def _flush(self, key: tuple[int, int], order_id: int) -> None:
        window = self.windows[key]
        try:
            await self.sleep(max(0.0, window.until - self.clock()))
            count, window.pending = window.pending, 0
            window.task = None
            if count > 0:
                window.until = self.clock() + self.window_s
                await self.send(digest_message(key[0], order_id, count))
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Chat bildirishnomasini birlashtirishda xato (order #%s)", order_id)
        finally:
            window.task = None
            self._prune()

    def _prune(self) -> None:
        """Eskirgan oynalarni tozalash (xotira cheksiz o'smasin)."""
        now = self.clock()
        for k in [k for k, w in self.windows.items() if w.task is None and now >= w.until]:
            del self.windows[k]

    async def drain(self) -> None:
        tasks = [w.task for w in self.windows.values() if w.task is not None]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    def cancel_all(self) -> None:
        for w in self.windows.values():
            if w.task is not None:
                w.task.cancel()
