"""`notification_service/handlers/support.py` — kimga qanday Telegram xabari boradi."""

from __future__ import annotations

import os

import pytest

# Format jihatdan yaroqli soxta token (aiogram ham tekshiradi); hech qayerga yuborilmaydi.
os.environ.setdefault("BOT_TOKEN", "123456789:pytest-fake-token")

from notification_service import config as n_config  # noqa: E402
from notification_service.handlers import support as h  # noqa: E402

ADMIN, MANAGER, OTHER_MANAGER, OWNER = 1, 2, 3, 100


@pytest.fixture(autouse=True)
def staff(monkeypatch):
    monkeypatch.setattr(n_config, "ADMIN_IDS", frozenset({ADMIN}))
    monkeypatch.setattr(n_config, "STAFF_NOTIFY_IDS", frozenset({MANAGER, OTHER_MANAGER, ADMIN}))


def _ids(out):
    return sorted(o.chat_id for o in out)


def test_created_goes_to_owner_and_all_staff_once():
    out = h.handle(
        "support.ticket_created",
        {"ticket_id": 5, "user_id": OWNER, "user_name": "Ali Valiyev", "user_role": "sender", "subject": "S"},
    )
    assert _ids(out) == [ADMIN, MANAGER, OTHER_MANAGER, OWNER]  # admin ikki marta emas
    staff_text = next(o.text for o in out if o.chat_id == MANAGER)
    assert "Ali Valiyev (sender)" in staff_text


def test_user_reply_goes_only_to_assignee():
    data = {
        "ticket_id": 5,
        "ticket_user_id": OWNER,
        "author_user_id": OWNER,
        "author_role": "sender",
        "author_name": "Ali",
        "assigned_to": MANAGER,
        "message": "Hali kelmadi",
        "attachments": 1,
    }
    out = h.handle("support.ticket_replied", data)
    assert _ids(out) == [MANAGER]
    assert "Ali (sender)" in out[0].text and "📎 Biriktirma: 1 ta" in out[0].text


def test_user_reply_without_assignee_goes_to_all_staff():
    out = h.handle(
        "support.ticket_replied",
        {"ticket_id": 5, "ticket_user_id": OWNER, "author_user_id": OWNER, "author_role": "sender", "message": "?"},
    )
    assert _ids(out) == [ADMIN, MANAGER, OTHER_MANAGER]


def test_staff_reply_goes_to_owner():
    out = h.handle(
        "support.ticket_replied",
        {"ticket_id": 5, "ticket_user_id": OWNER, "author_user_id": MANAGER, "author_role": "manager", "message": "Ok"},
    )
    assert _ids(out) == [OWNER]


def test_staff_writing_in_own_ticket_notifies_staff():
    out = h.handle(
        "support.ticket_replied",
        {"ticket_id": 5, "ticket_user_id": MANAGER, "author_user_id": MANAGER, "author_role": "manager", "message": "x"},
    )
    assert OWNER not in _ids(out) and _ids(out)


def test_status_change_by_owner_is_silent():
    base = {"ticket_id": 5, "ticket_user_id": OWNER, "new_status": "closed", "subject": "S"}
    assert h.handle("support.ticket_status_changed", {**base, "changed_by_user_id": OWNER}) == []
    out = h.handle("support.ticket_status_changed", {**base, "changed_by_user_id": MANAGER})
    assert _ids(out) == [OWNER] and "hal qilindi" in out[0].text
    # "Ochiq" ga qaytarish — foydalanuvchiga shovqin emas.
    assert h.handle("support.ticket_status_changed", {**base, "new_status": "open", "changed_by_user_id": MANAGER}) == []
