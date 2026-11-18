"""Holat o'tish qoidalari, o'qilmaganlar, biriktirish va ro'yxat tartibi."""

from __future__ import annotations

import pytest

from support_service import rules
from support_service.models import TicketStatus as S

from .conftest import ADMIN, MANAGER, OWNER, STRANGER, auth, new_ticket


# ─── Qoidalar matritsasi ─────────────────────────────────────────────────────


@pytest.mark.parametrize("target", list(S))
def test_closed_is_terminal(target):
    assert not rules.can_transition(S.CLOSED, target, is_staff=True)
    assert not rules.can_transition(S.CLOSED, target, is_staff=False)


@pytest.mark.parametrize("current", [S.OPEN, S.IN_PROGRESS, S.RESOLVED])
def test_owner_can_only_close(current):
    assert rules.allowed_transitions(current, is_staff=False) == {S.CLOSED}


def test_staff_can_reopen_resolved():
    assert rules.can_transition(S.RESOLVED, S.IN_PROGRESS, is_staff=True)


# ─── HTTP orqali ─────────────────────────────────────────────────────────────


async def _set_status(client, ticket_id, status, user):
    return await client.patch(
        f"/support/tickets/{ticket_id}/status", json={"status": status}, headers=auth(user)
    )


async def test_owner_closes_own_ticket(client, actors, events):
    ticket = await new_ticket(client)
    assert ticket["allowed_statuses"] == ["closed"]

    resp = await _set_status(client, ticket["id"], "closed", OWNER)
    assert resp.status_code == 200
    assert resp.json()["status"] == "closed"
    assert resp.json()["allowed_statuses"] == []
    assert events[-1][0] == "support.ticket_status_changed"
    assert events[-1][1]["changed_by_user_id"] == OWNER


async def test_owner_cannot_set_other_statuses(client, actors):
    ticket = await new_ticket(client)
    resp = await _set_status(client, ticket["id"], "resolved", OWNER)
    assert resp.status_code == 409


async def test_stranger_cannot_close(client, actors):
    ticket = await new_ticket(client)
    assert (await _set_status(client, ticket["id"], "closed", STRANGER)).status_code == 404


async def test_closed_cannot_be_reopened(client, actors):
    ticket = await new_ticket(client)
    await _set_status(client, ticket["id"], "closed", MANAGER)
    resp = await _set_status(client, ticket["id"], "open", ADMIN)
    assert resp.status_code == 409
    msg = await client.post(
        f"/support/tickets/{ticket['id']}/messages", json={"body": "yana"}, headers=auth(OWNER)
    )
    assert msg.status_code == 409


async def test_resolved_blocks_messages_until_reopened(client, actors):
    ticket = await new_ticket(client)
    assert (await _set_status(client, ticket["id"], "resolved", MANAGER)).status_code == 200
    path = f"/support/tickets/{ticket['id']}/messages"
    assert (await client.post(path, json={"body": "hal bo'lmadi"}, headers=auth(OWNER))).status_code == 409

    assert (await _set_status(client, ticket["id"], "in_progress", MANAGER)).status_code == 200
    assert (await client.post(path, json={"body": "hal bo'lmadi"}, headers=auth(OWNER))).status_code == 201


async def test_same_status_is_noop_without_event(client, actors, events):
    ticket = await new_ticket(client)
    before = len(events)
    resp = await _set_status(client, ticket["id"], "open", MANAGER)
    assert resp.status_code == 200
    assert len(events) == before


# ─── Javobdan keyingi server o'zgarishlari ───────────────────────────────────


async def test_staff_reply_moves_to_in_progress_and_assigns(client, actors):
    ticket = await new_ticket(client)
    resp = await client.post(
        f"/support/tickets/{ticket['id']}/messages", json={"body": "Tekshiryapmiz"}, headers=auth(MANAGER)
    )
    assert resp.status_code == 201
    data = resp.json()
    # Javob tanasida murojaatning YANGI holati — UI uni darhol ko'rsatadi.
    assert data["ticket"]["status"] == "in_progress"
    assert data["ticket"]["assigned_to"] == MANAGER
    assert data["ticket"]["assigned_name"] == "Menejer Madina"
    assert data["author_name"] == "Menejer Madina"


async def test_message_bumps_last_message_at_and_order(client, actors):
    first = await new_ticket(client)
    second = await new_ticket(client)

    listing = (await client.get("/support/tickets", headers=auth(OWNER))).json()
    assert [t["id"] for t in listing["items"]] == [second["id"], first["id"]]

    await client.post(
        f"/support/tickets/{first['id']}/messages", json={"body": "Hali javob yo'q"}, headers=auth(OWNER)
    )
    listing = (await client.get("/support/tickets", headers=auth(OWNER))).json()
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
    item = (await client.get("/support/tickets", headers=auth(OWNER))).json()["items"][0]
    assert item["unread_count"] == 2

    # Ochish — o'qildi.
    await client.get(f"/support/tickets/{tid}", headers=auth(OWNER))
    assert (await client.get("/support/unread", headers=auth(OWNER))).json() == {"tickets": 0, "messages": 0}


async def test_unread_for_staff(client, actors):
    ticket = await new_ticket(client)
    tid = ticket["id"]

    # Yangi murojaat — xodim uchun o'qilmagan (asosiy matn).
    staff_unread = (await client.get("/support/unread?as_staff=true", headers=auth(MANAGER))).json()
    assert staff_unread == {"tickets": 1, "messages": 1}

    await client.get(f"/support/tickets/{tid}", headers=auth(MANAGER))
    assert (await client.get("/support/unread?as_staff=true", headers=auth(MANAGER))).json()["messages"] == 0

    await client.post(f"/support/tickets/{tid}/messages", json={"body": "Yana savol"}, headers=auth(OWNER))
    item = (await client.get("/support/tickets", headers=auth(ADMIN))).json()["items"][0]
    assert item["unread_count"] == 1

    # Explicit "read" (ochiq chatga WS orqali xabar kelganda).
    assert (await client.post(f"/support/tickets/{tid}/read", headers=auth(ADMIN))).status_code == 204
    item = (await client.get("/support/tickets", headers=auth(ADMIN))).json()["items"][0]
    assert item["unread_count"] == 0


async def test_own_messages_are_never_unread(client, actors):
    ticket = await new_ticket(client)
    await client.post(f"/support/tickets/{ticket['id']}/messages", json={"body": "Men"}, headers=auth(OWNER))
    assert (await client.get("/support/unread", headers=auth(OWNER))).json()["messages"] == 0


async def test_read_does_not_touch_updated_at(client, actors):
    ticket = await new_ticket(client)
    await client.get(f"/support/tickets/{ticket['id']}", headers=auth(MANAGER))
    again = (await client.get(f"/support/tickets/{ticket['id']}", headers=auth(OWNER))).json()
    assert again["updated_at"] == ticket["updated_at"]


# ─── O'ziga olish ────────────────────────────────────────────────────────────


async def test_assign_and_filter(client, actors):
    t1 = await new_ticket(client)
    await new_ticket(client)

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
