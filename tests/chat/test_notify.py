"""`chat.message_created` → Telegram bildirishnomasi (notification_service, 1 daqiqada birlashtirib)."""

from __future__ import annotations

import asyncio
import os

import pytest

os.environ.setdefault("BOT_TOKEN", "123456789:pytest-fake-token")

from notification_service import config as n_config  # noqa: E402
from contracts import events as nc  # noqa: E402
from notification_service.handlers.chat import ChatCoalescer, chat_button  # noqa: E402


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0
        self.release = asyncio.Event()

    def __call__(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        # Oyna tugashini test o'zi boshqaradi.
        await self.release.wait()
        self.now += seconds


@pytest.fixture
def harness(monkeypatch):
    monkeypatch.setattr(n_config, "WEBAPP_URL", "https://yuk.example.uz")
    monkeypatch.setattr(n_config, "TELEGRAM_MINIAPP_LINK", "")
    clock = Clock()
    sent = []

    async def send(item):
        sent.append(item)

    return ChatCoalescer(send, clock=clock, sleep=clock.sleep), clock, sent


def event(order_id=42, recipient=2002, **extra):
    return {
        "order_id": order_id,
        "message_id": 1,
        "kind": "text",
        "preview": "Salom, qachon kelasiz?",
        "sender_user_id": 1001,
        "sender_role": "sender",
        "recipient_user_id": recipient,
        "recipient_driver_id": 77,
        "recipient_online": False,
        **extra,
    }


async def test_first_message_immediate_rest_coalesced(harness):
    notifier, clock, sent = harness
    for _ in range(5):
        await notifier.handle(event())

    assert len(sent) == 1
    first = sent[0]
    assert first.chat_id == 2002
    assert "Buyurtma #42" in first.text and "Yuk egasi: Salom" in first.text
    assert first.reply_markup["inline_keyboard"][0][0]["web_app"]["url"] == "https://yuk.example.uz/orders/42/chat"

    clock.release.set()
    await notifier.drain()
    assert len(sent) == 2 and "yana 4 ta yangi xabar" in sent[1].text


async def test_after_window_new_first_message(harness):
    notifier, clock, sent = harness
    await notifier.handle(event())
    clock.now += 61
    await notifier.handle(event(preview="yana"))
    assert len(sent) == 2 and "yana" in sent[1].text and "ta yangi xabar" not in sent[1].text


async def test_windows_are_per_recipient_and_order(harness):
    notifier, _, sent = harness
    await notifier.handle(event(order_id=1))
    await notifier.handle(event(order_id=2))
    await notifier.handle(event(order_id=1, recipient=1001))
    assert len(sent) == 3


async def test_single_message_no_digest(harness):
    notifier, clock, sent = harness
    await notifier.handle(event())
    clock.release.set()
    await notifier.drain()
    assert len(sent) == 1


async def test_online_or_unknown_recipient_not_notified(harness):
    notifier, _, sent = harness
    await notifier.handle(event(recipient_online=True))
    await notifier.handle(event(recipient=None))
    await notifier.handle({"kind": "text"})
    assert sent == []


def test_buttons(monkeypatch):
    monkeypatch.setattr(n_config, "TELEGRAM_MINIAPP_LINK", "https://t.me/YukBot/app")
    assert chat_button(7)["inline_keyboard"][0][0]["url"] == "https://t.me/YukBot/app?startapp=chat_7"
    monkeypatch.setattr(n_config, "TELEGRAM_MINIAPP_LINK", "")
    monkeypatch.setattr(n_config, "WEBAPP_URL", "http://localhost:8000")
    assert chat_button(7) is None


def test_contract_matches_chat_service():
    from chat_service import queue as chat_queue

    assert nc.EVENTS_EXCHANGE == chat_queue.EVENTS_EXCHANGE
    assert nc.EVENT_CHAT_MESSAGE_CREATED == chat_queue.EVENT_CHAT_MESSAGE_CREATED
    assert nc.CHAT_NOTIFICATIONS_QUEUE == chat_queue.CHAT_NOTIFICATIONS_QUEUE
    assert nc.CHAT_NOTIFICATIONS_PATTERN == chat_queue.CHAT_NOTIFICATIONS_PATTERN
