"""Bitta foydalanuvchi — bitta chat: holatlar, qayta ochilish, o'qilmaganlar, biriktirish."""

from __future__ import annotations

import pytest

from support_service import rules
from support_service.models import TicketStatus as S

from .conftest import ADMIN, MANAGER, OWNER, STRANGER, auth, new_ticket


# ─── Qoidalar matritsasi ─────────────────────────────────────────────────────


@pytest.mark.parametrize("current", list(S))
def test_owner_cannot_change_status(current):
    assert rules.allowed_transitions(current, is_staff=False) == frozenset()


@pytest.mark.parametrize("current", list(S))
def test_staff_moves_freely_but_never_to_closed(current):
    allowed = rules.allowed_transitions(current, is_staff=True)
    assert S.CLOSED not in allowed
    assert current not in allowed
    assert allowed == {S.OPEN, S.IN_PROGRESS, S.RESOLVED} - {current}


# ─── Bitta chat ──────────────────────────────────────────────────────────────


async def _say(client, text, user=OWNER, **extra):
    resp = await client.post(
        "/support/conversation/messages", json={"body": text, **extra}, headers=auth(user)
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def test_conversation_is_null_until_first_message(client, actors):
    resp = await client.get("/support/conversation", headers=auth(OWNER))
    assert resp.status_code == 200
    assert resp.json() == {"conversation": None}
    assert (await client.get("/support/conversation/messages", headers=auth(OWNER))).json() == {
        "items": [],
        "has_more": False,
    }


async def test_first_message_creates_chat_once(client, actors, events):
    first = await _say(client, "Salom, savolim bor")
    second = await _say(client, "Yana bir savol")
    assert first["ticket_id"] == second["ticket_id"]

    # Hodisalar: birinchi xabar — "chat yaratildi" (xodimlarga), keyingisi — "javob".
    names = [e for e, _ in events]
    assert names == ["support.ticket_created", "support.ticket_replied"]
    assert events[0][1]["body"] == "Salom, savolim bor"

    conv = (await client.get("/support/conversation", headers=auth(OWNER))).json()["conversation"]
    assert conv["id"] == first["ticket_id"]
    assert [m["body"] for m in conv["messages"]] == ["Salom, savolim bor", "Yana bir savol"]
    assert conv["allowed_statuses"] == []

    listing = (await client.get("/support/tickets", headers=auth(ADMIN))).json()
    assert listing["total"] == 1


async def test_legacy_ticket_create_appends_to_same_chat(client, actors):
    first = await new_ticket(client)
    second = await new_ticket(client, subject="Yuk shikastlandi", body="Qutisi ezilgan holda keldi")
    assert first["id"] == second["id"]
    bodies = [m["body"] for m in second["messages"]]
    assert bodies == [
        "📌 Haydovchi kelmadi\nSoat 10 da kelishi kerak edi",
        "📌 Yuk shikastlandi\nQutisi ezilgan holda keldi",
    ]


async def test_each_user_has_own_chat(client, actors):
    mine = await _say(client, "Men")
    theirs = await _say(client, "Men ham", user=STRANGER)
    assert mine["ticket_id"] != theirs["ticket_id"]
    own = (await client.get("/support/conversation", headers=auth(STRANGER))).json()["conversation"]
    assert [m["body"] for m in own["messages"]] == ["Men ham"]


# ─── Holatlar ────────────────────────────────────────────────────────────────


async def _set_status(client, ticket_id, status, user):
    return await client.patch(
        f"/support/tickets/{ticket_id}/status", json={"status": status}, headers=auth(user)
    )


async def test_owner_cannot_set_status(client, actors):
    ticket = await new_ticket(client)
    for target in ("resolved", "closed", "in_progress"):
        assert (await _set_status(client, ticket["id"], target, OWNER)).status_code == 409


async def test_stranger_gets_404(client, actors):
    ticket = await new_ticket(client)
    assert (await _set_status(client, ticket["id"], "resolved", STRANGER)).status_code == 404


async def test_staff_cannot_close(client, actors):
    ticket = await new_ticket(client)
    assert (await _set_status(client, ticket["id"], "closed", MANAGER)).status_code == 409


async def test_owner_message_reopens_resolved_chat(client, actors, events):
    ticket = await new_ticket(client)
    resp = await _set_status(client, ticket["id"], "resolved", MANAGER)
    assert resp.status_code == 200
    assert events[-1][0] == "support.ticket_status_changed"

    data = await _say(client, "Muammo yana takrorlandi")
    assert data["ticket"]["status"] == "open"
    assert events[-1][0] == "support.ticket_replied"
    assert events[-1][1]["reopened"] is True


async def test_staff_message_keeps_resolved_chat_resolved(client, actors):
    ticket = await new_ticket(client)
    await _set_status(client, ticket["id"], "resolved", MANAGER)
    resp = await client.post(
        f"/support/tickets/{ticket['id']}/messages", json={"body": "Yana nima kerak?"}, headers=auth(MANAGER)
    )
    assert resp.status_code == 201
    assert resp.json()["ticket"]["status"] == "resolved"


async def test_same_status_is_noop_without_event(client, actors, events):
    ticket = await new_ticket(client)
    before = len(events)
    resp = await _set_status(client, ticket["id"], "open", MANAGER)
    assert resp.status_code == 200
    assert len(events) == before


async def test_staff_reply_moves_to_in_progress_and_assigns(client, actors):
    ticket = await new_ticket(client)
    resp = await client.post(
        f"/support/tickets/{ticket['id']}/messages", json={"body": "Tekshiryapmiz"}, headers=auth(MANAGER)
    )
    assert resp.status_code == 201
    data = resp.json()
    # Javob tanasida chatning YANGI holati — UI uni darhol ko'rsatadi.
    assert data["ticket"]["status"] == "in_progress"
    assert data["ticket"]["assigned_to"] == MANAGER
    assert data["ticket"]["assigned_name"] == "Menejer Madina"
    assert data["author_name"] == "Menejer Madina"


async def test_message_bumps_chat_in_staff_list(client, actors):
    first = await new_ticket(client)
    second = await new_ticket(client, user_id=STRANGER)

    listing = (await client.get("/support/tickets", headers=auth(ADMIN))).json()
    assert [t["id"] for t in listing["items"]] == [second["id"], first["id"]]

    await _say(client, "Hali javob yo'q")
    listing = (await client.get("/support/tickets", headers=auth(ADMIN))).json()
    assert [t["id"] for t in listing["items"]] == [first["id"], second["id"]]
    top = listing["items"][0]
    assert top["last_message"]["body"] == "Hali javob yo'q"
    assert top["last_message_at"] > first["last_message_at"]
    assert top["updated_at"] > first["updated_at"]


# ─── O'qilmaganlar ───────────────────────────────────────────────────────────


async def test_unread_for_owner(client, actors):
    ticket = await new_ticket(client)
    tid = ticket["id"]
    assert (await client.get("/support/unread", headers=auth(OWNER))).json() == {"tickets": 0, "messages": 0}

    for text in ("Salom", "Haydovchi bilan bog'landik"):
        await client.post(f"/support/tickets/{tid}/messages", json={"body": text}, headers=auth(MANAGER))

    assert (await client.get("/support/unread", headers=auth(OWNER))).json() == {"tickets": 1, "messages": 2}

    # O'z chatini ochish — o'qildi.
    await client.get("/support/conversation", headers=auth(OWNER))
    assert (await client.get("/support/unread", headers=auth(OWNER))).json() == {"tickets": 0, "messages": 0}

    await client.post(f"/support/tickets/{tid}/messages", json={"body": "Yana"}, headers=auth(MANAGER))
    assert (await client.post("/support/conversation/read", headers=auth(OWNER))).status_code == 204
    assert (await client.get("/support/unread", headers=auth(OWNER))).json()["messages"] == 0


async def test_unread_for_staff(client, actors):
    ticket = await new_ticket(client)
    tid = ticket["id"]

    # Yangi chat — birinchi xabar xodim uchun o'qilmagan.
    staff_unread = (await client.get("/support/unread?as_staff=true", headers=auth(MANAGER))).json()
    assert staff_unread == {"tickets": 1, "messages": 1}

    await client.get(f"/support/tickets/{tid}", headers=auth(MANAGER))
    assert (await client.get("/support/unread?as_staff=true", headers=auth(MANAGER))).json()["messages"] == 0

    await _say(client, "Yana savol")
    item = (await client.get("/support/tickets", headers=auth(ADMIN))).json()["items"][0]
    assert item["unread_count"] == 1

    # Explicit "read" (ochiq chatga WS orqali xabar kelganda).
    assert (await client.post(f"/support/tickets/{tid}/read", headers=auth(ADMIN))).status_code == 204
    item = (await client.get("/support/tickets", headers=auth(ADMIN))).json()["items"][0]
    assert item["unread_count"] == 0


async def test_own_messages_are_never_unread(client, actors):
    await new_ticket(client)
    await _say(client, "Men")
    assert (await client.get("/support/unread", headers=auth(OWNER))).json()["messages"] == 0


async def test_read_does_not_touch_updated_at(client, actors):
    ticket = await new_ticket(client)
    await client.get(f"/support/tickets/{ticket['id']}", headers=auth(MANAGER))
    again = (await client.get(f"/support/tickets/{ticket['id']}", headers=auth(OWNER))).json()
    assert again["updated_at"] == ticket["updated_at"]


# ─── Buyurtma konteksti ──────────────────────────────────────────────────────


async def test_order_id_is_kept_on_message_and_chat(client, actors):
    actors.order_access[77] = {OWNER}
    data = await _say(client, "Shu buyurtma bo'yicha", order_id=77)
    assert data["order_id"] == 77
    assert data["ticket"]["order_id"] == 77


async def test_foreign_order_on_message_is_rejected(client, actors):
    actors.order_access[77] = {STRANGER}
    resp = await client.post(
        "/support/conversation/messages", json={"body": "x", "order_id": 77}, headers=auth(OWNER)
    )
    assert resp.status_code == 404


# ─── O'ziga olish ────────────────────────────────────────────────────────────


async def test_assign_and_filter(client, actors):
    t1 = await new_ticket(client)
    await new_ticket(client, user_id=STRANGER)

    resp = await client.post(f"/support/tickets/{t1['id']}/assign", headers=auth(ADMIN))
    assert resp.status_code == 200
    assert resp.json()["assigned_to"] == ADMIN

    mine = (await client.get("/support/tickets?assigned=me", headers=auth(ADMIN))).json()
    assert [t["id"] for t in mine["items"]] == [t1["id"]]
    free = (await client.get("/support/tickets?assigned=none", headers=auth(ADMIN))).json()
    assert free["total"] == 1

    resp = await client.delete(f"/support/tickets/{t1['id']}/assign", headers=auth(ADMIN))
    assert resp.json()["assigned_to"] is None


async def test_owner_cannot_assign(client, actors):
    ticket = await new_ticket(client)
    assert (await client.post(f"/support/tickets/{ticket['id']}/assign", headers=auth(OWNER))).status_code == 403


async def test_same_client_id_is_written_once(client, actors, events):
    """WS javobi kelmay REST bilan qayta yuborilgan xabar ikki marta yozilmaydi."""
    first = await _say(client, "Salom", client_id="abc-1")
    again = await _say(client, "Salom", client_id="abc-1")
    assert again["id"] == first["id"]
    other = await _say(client, "Salom", client_id="abc-2")
    assert other["id"] != first["id"]

    conv = (await client.get("/support/conversation", headers=auth(OWNER))).json()["conversation"]
    assert [m["body"] for m in conv["messages"]] == ["Salom", "Salom"]
    # Takror hodisa ham yubormaydi.
    assert [e for e, _ in events] == ["support.ticket_created", "support.ticket_replied"]
    # Boshqa foydalanuvchi shu client_id bilan o'z xabarini yoza oladi.
    theirs = await _say(client, "Salom", user=STRANGER, client_id="abc-1")
    assert theirs["ticket_id"] != first["ticket_id"]
