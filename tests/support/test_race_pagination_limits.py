"""Birinchi xabar poygasi, sahifalash va rate-limit."""

from __future__ import annotations

import asyncio

from sqlalchemy import func, select

from support_service.db import async_session
from support_service.models import SupportMessage, SupportTicket

from .conftest import MANAGER, OWNER, STRANGER, auth, new_ticket


async def test_concurrent_first_messages_create_one_chat(client, actors):
    """Bir vaqtda kelgan birinchi xabarlar ikkita chat yaratmaydi (`user_id` yagona,
    `INSERT ... ON CONFLICT DO NOTHING` + qulf)."""
    results = await asyncio.gather(
        *[
            client.post("/support/conversation/messages", json={"body": f"#{i}"}, headers=auth(OWNER))
            for i in range(5)
        ]
    )
    assert [r.status_code for r in results] == [201] * 5
    assert len({r.json()["ticket_id"] for r in results}) == 1

    async with async_session() as db:
        chats = await db.scalar(select(func.count(SupportTicket.id)).where(SupportTicket.user_id == OWNER))
        messages = await db.scalar(select(func.count(SupportMessage.id)))
    assert chats == 1 and messages == 5


async def test_concurrent_replies_all_land(client, actors):
    ticket = await new_ticket(client)
    tid = ticket["id"]
    results = await asyncio.gather(
        *[
            client.post(f"/support/tickets/{tid}/messages", json={"body": f"#{i}"}, headers=auth(OWNER))
            for i in range(5)
        ]
    )
    assert [r.status_code for r in results] == [201] * 5
    detail = (await client.get(f"/support/tickets/{tid}", headers=auth(OWNER))).json()
    # + birinchi savol (murojaat matni ham chatdagi xabar).
    assert len(detail["messages"]) == 6


# ─── Sahifalash ──────────────────────────────────────────────────────────────


async def test_ticket_list_has_total(client, actors):
    # Har foydalanuvchiga bitta chat: bir odam ko'p yozsa ham ro'yxatda bitta.
    for _ in range(3):
        await new_ticket(client, OWNER)
    await new_ticket(client, STRANGER)
    actors.user(1003, "driver", "Haydovchi")
    await new_ticket(client, 1003)

    own = (await client.get("/support/tickets", headers=auth(OWNER))).json()
    assert own["total"] == 1

    page = (await client.get("/support/tickets?limit=2", headers=auth(MANAGER))).json()
    assert page["total"] == 3
    assert len(page["items"]) == 2
    page2 = (await client.get("/support/tickets?limit=2&offset=2", headers=auth(MANAGER))).json()
    assert len(page2["items"]) == 1


async def test_messages_are_paginated(client, actors):
    ticket = await new_ticket(client)
    tid = ticket["id"]
    # Ko'p xabar — rate-limit xodimda kengroq, shuning uchun xodim yozadi.
    for i in range(7):
        r = await client.post(f"/support/tickets/{tid}/messages", json={"body": f"m{i}"}, headers=auth(MANAGER))
        assert r.status_code == 201

    detail = (await client.get(f"/support/tickets/{tid}?messages_limit=3", headers=auth(OWNER))).json()
    assert [m["body"] for m in detail["messages"]] == ["m4", "m5", "m6"]
    assert detail["has_more_messages"] is True

    older = (
        await client.get(
            f"/support/tickets/{tid}/messages?before_id={detail['messages'][0]['id']}&limit=3",
            headers=auth(OWNER),
        )
    ).json()
    assert [m["body"] for m in older["items"]] == ["m1", "m2", "m3"]
    assert older["has_more"] is True

    oldest = (
        await client.get(
            f"/support/tickets/{tid}/messages?before_id={older['items'][0]['id']}&limit=3",
            headers=auth(OWNER),
        )
    ).json()
    # Eng boshida — chatdagi birinchi savol.
    assert [m["body"] for m in oldest["items"]] == ["📌 Haydovchi kelmadi\nSoat 10 da kelishi kerak edi", "m0"]
    assert oldest["has_more"] is False


# ─── Rate-limit ──────────────────────────────────────────────────────────────


async def test_message_rate_limit(client, actors):
    ticket = await new_ticket(client)
    path = f"/support/tickets/{ticket['id']}/messages"
    codes = [
        (await client.post(path, json={"body": f"x{i}"}, headers=auth(OWNER))).status_code for i in range(11)
    ]
    assert codes[:10] == [201] * 10
    assert codes[10] == 429


async def test_ticket_rate_limit(client, actors):
    for _ in range(5):
        await new_ticket(client, OWNER)
    resp = await client.post(
        "/support/tickets", json={"subject": "Oltinchi", "body": "Yana bir murojaat"}, headers=auth(OWNER)
    )
    assert resp.status_code == 429
    assert "Retry-After" in resp.headers
    # Boshqa foydalanuvchiga ta'sir qilmaydi.
    await new_ticket(client, STRANGER)
