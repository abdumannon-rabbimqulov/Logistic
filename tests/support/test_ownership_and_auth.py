"""Buyurtma egaligi va bloklangan foydalanuvchi tekshiruvi."""

from __future__ import annotations

from support_service import core_client

from .conftest import ADMIN, MANAGER, OWNER, STRANGER, auth, make_token, new_ticket


# ─── Buyurtma egaligi ────────────────────────────────────────────────────────


async def test_foreign_order_is_rejected(client, actors, events):
    actors.order_access[77] = {OWNER}

    resp = await client.post(
        "/support/tickets",
        json={"subject": "Begona buyurtma", "body": "Bu buyurtma haqida", "order_id": 77},
        headers=auth(STRANGER),
    )
    assert resp.status_code == 404
    # Murojaat yaratilmagan va hodisa chiqmagan.
    listing = await client.get("/support/tickets", headers=auth(MANAGER))
    assert listing.json()["total"] == 0
    assert events == []


async def test_own_order_is_accepted(client, actors):
    actors.order_access[77] = {OWNER}
    ticket = await new_ticket(client, OWNER, order_id=77)
    assert ticket["order_id"] == 77
    assert ticket["user_name"] == "Ali Valiyev"


async def test_staff_can_open_ticket_for_any_order(client, actors):
    ticket = await new_ticket(client, MANAGER, order_id=500)
    assert ticket["order_id"] == 500


async def test_core_down_while_checking_order_returns_503(client, actors):
    actors.order_access[77] = {OWNER}
    # Holat keshda bo'lsin, faqat buyurtma tekshiruvi yiqilsin.
    await client.get("/support/tickets", headers=auth(OWNER))
    actors.available = False
    resp = await client.post(
        "/support/tickets",
        json={"subject": "Buyurtma", "body": "Muammo bor edi", "order_id": 77},
        headers=auth(OWNER),
    )
    assert resp.status_code == 503


# ─── Bloklangan / faol emas ──────────────────────────────────────────────────


async def test_banned_user_is_rejected(client, actors):
    actors.user(OWNER, "sender", active=False)
    resp = await client.get("/support/tickets", headers=auth(OWNER))
    assert resp.status_code == 403


async def test_block_applies_after_cache_expires(client, actors):
    assert (await client.get("/support/tickets", headers=auth(OWNER))).status_code == 200

    actors.user(OWNER, "sender", active=False)
    # Kesh ichida — hali o'tadi (core'ga qayta borilmaydi).
    calls = actors.status_calls
    assert (await client.get("/support/tickets", headers=auth(OWNER))).status_code == 200
    assert actors.status_calls == calls

    # Kesh muddati tugadi (TTL ~60 s) — endi bloklangan.
    await core_client.invalidate_user_status(OWNER)
    assert (await client.get("/support/tickets", headers=auth(OWNER))).status_code == 403


async def test_core_down_uses_last_known_status(client, actors):
    actors.user(OWNER, "sender", active=False)
    assert (await client.get("/support/tickets", headers=auth(OWNER))).status_code == 403

    await core_client.invalidate_user_status(OWNER)
    actors.available = False
    # Core o'chiq — oxirgi ma'lum holat (bloklangan) qo'llanadi, fail-open EMAS.
    assert (await client.get("/support/tickets", headers=auth(OWNER))).status_code == 403


async def test_core_down_without_history_falls_back_to_jwt(client, actors):
    actors.available = False
    assert (await client.get("/support/tickets", headers=auth(OWNER))).status_code == 200


async def test_role_comes_from_core_not_token(client, actors):
    # Token "admin" deydi, lekin core'da u oddiy mijoz — hamma murojaatlarni ko'rmasin.
    await new_ticket(client, STRANGER)
    resp = await client.get("/support/tickets", headers=auth(OWNER, role="admin"))
    assert resp.status_code == 200
    assert resp.json()["total"] == 0


async def test_refresh_token_is_rejected(client, actors):
    token = make_token(OWNER, token_type="refresh")
    resp = await client.get("/support/tickets", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 401


async def test_stranger_cannot_see_ticket(client, actors):
    ticket = await new_ticket(client, OWNER)
    for path in (f"/support/tickets/{ticket['id']}", f"/support/tickets/{ticket['id']}/messages"):
        assert (await client.get(path, headers=auth(STRANGER))).status_code == 404
    resp = await client.post(
        f"/support/tickets/{ticket['id']}/messages", json={"body": "salom"}, headers=auth(STRANGER)
    )
    assert resp.status_code == 404
    assert (await client.get(f"/support/tickets/{ticket['id']}", headers=auth(ADMIN))).status_code == 200
