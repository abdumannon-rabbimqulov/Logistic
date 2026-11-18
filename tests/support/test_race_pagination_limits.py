"""Javob/yopish poygasi, sahifalash va rate-limit."""

from __future__ import annotations

import asyncio

from sqlalchemy import func, select

from support_service import crud
from support_service.db import async_session
from support_service.models import SupportMessage, TicketStatus

from .conftest import MANAGER, OWNER, STRANGER, auth, new_ticket


async def test_reply_waits_for_close_lock_and_is_rejected(client, actors):
    """Yopish tranzaksiyasi qulfni ushlab turganda javob kutadi va keyin 409 oladi.

    Qulfsiz versiyada javob "ochiq" holatni ko'rib INSERT qilib ulgurardi va
    yopilgan murojaatda yangi xabar paydo bo'lardi.
    """
    ticket = await new_ticket(client)
    tid = ticket["id"]

    async with async_session() as closer:
        locked = await crud.get_ticket(closer, tid, for_update=True)
        locked.status = TicketStatus.CLOSED
        await closer.flush()  # hali COMMIT yo'q — qator qulflangan

        reply = asyncio.create_task(
            client.post(f"/support/tickets/{tid}/messages", json={"body": "Kech qoldim"}, headers=auth(OWNER))
        )
        await asyncio.sleep(0.3)
        assert not reply.done(), "javob qulfni kutishi kerak edi"

        await closer.commit()

    resp = await asyncio.wait_for(reply, timeout=5)
    assert resp.status_code == 409

    async with async_session() as db:
        count = await db.scalar(select(func.count(SupportMessage.id)).where(SupportMessage.ticket_id == tid))
    assert count == 0


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
    assert len(detail["messages"]) == 5


# ─── Sahifalash ──────────────────────────────────────────────────────────────


async def test_ticket_list_has_total(client, actors):
    for _ in range(3):
        await new_ticket(client, OWNER)
    await new_ticket(client, STRANGER)

    page = (await client.get("/support/tickets?limit=2", headers=auth(OWNER))).json()
    assert page["total"] == 3
    assert len(page["items"]) == 2
    page2 = (await client.get("/support/tickets?limit=2&offset=2", headers=auth(OWNER))).json()
    assert len(page2["items"]) == 1
    assert (await client.get("/support/tickets", headers=auth(MANAGER))).json()["total"] == 4


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
    assert [m["body"] for m in oldest["items"]] == ["m0"]
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
