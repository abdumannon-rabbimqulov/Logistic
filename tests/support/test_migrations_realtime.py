"""Alembic baseline, real vaqt (WS) va buyurtma hodisalari yorliqlari."""

from __future__ import annotations

import asyncio
import functools

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from support_service import main as support_main
from support_service import queue, realtime
from support_service.models import Base

from .conftest import (
    MANAGER,
    OWNER,
    STRANGER,
    TEST_DB_URL,
    alembic_config,
    auth,
    make_token,
    new_ticket,
    recreate_database,
)

# Avvalgi `Base.metadata.create_all` qurgan sxema (alembic'dan oldingi prod holati).
OLD_SCHEMA = [
    "CREATE TYPE ticketstatus AS ENUM ('open', 'in_progress', 'resolved', 'closed')",
    "CREATE TYPE ticketpriority AS ENUM ('low', 'normal', 'high', 'urgent')",
    """CREATE TABLE support_tickets (
        id SERIAL PRIMARY KEY, user_id BIGINT NOT NULL, user_role VARCHAR(20),
        order_id INTEGER, subject VARCHAR(200) NOT NULL, body TEXT NOT NULL,
        status ticketstatus NOT NULL, priority ticketpriority NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now())""",
    "CREATE INDEX ix_support_tickets_user_id ON support_tickets (user_id)",
    "CREATE INDEX ix_support_tickets_order_id ON support_tickets (order_id)",
    "CREATE INDEX ix_support_tickets_status ON support_tickets (status)",
    """CREATE TABLE support_messages (
        id SERIAL PRIMARY KEY,
        ticket_id INTEGER NOT NULL REFERENCES support_tickets(id) ON DELETE CASCADE,
        author_user_id BIGINT, author_role VARCHAR(20), is_system BOOLEAN NOT NULL,
        body TEXT NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now())""",
    "CREATE INDEX ix_support_messages_ticket_id ON support_messages (ticket_id)",
    """INSERT INTO support_tickets (user_id, user_role, subject, body, status, priority, created_at)
       VALUES (42, 'sender', 'Eski', 'Eski murojaat matni', 'open', 'normal', '2026-01-01T10:00:00Z')""",
    """INSERT INTO support_messages (ticket_id, author_user_id, author_role, is_system, body, created_at)
       VALUES (1, 7, 'admin', false, 'Eski javob', '2026-01-02T10:00:00Z')""",
    # Shu foydalanuvchining ikkinchi murojaati (yopilgan) — chatga birlashadi.
    """INSERT INTO support_tickets (user_id, user_role, subject, body, status, priority, created_at)
       VALUES (42, 'sender', 'Ikkinchi', 'Yana muammo', 'closed', 'high', '2026-01-03T10:00:00Z')""",
    """INSERT INTO support_messages (ticket_id, author_user_id, author_role, is_system, body, created_at)
       VALUES (2, 42, 'sender', false, 'Ikkinchiga izoh', '2026-01-03T11:00:00Z')""",
    # Boshqa foydalanuvchi — alohida chat bo'lib qoladi.
    """INSERT INTO support_tickets (user_id, user_role, subject, body, status, priority, created_at)
       VALUES (43, 'driver', 'Haydovchi', 'Haydovchi savoli', 'resolved', 'low', '2026-01-04T10:00:00Z')""",
]


def _migration_db_url() -> str:
    from sqlalchemy.engine import make_url

    url = make_url(TEST_DB_URL)
    return url.set(database=f"{url.database}_migrations").render_as_string(hide_password=False)


async def _exec(url: str, statements: list[str]) -> None:
    engine = create_async_engine(url, poolclass=NullPool)
    async with engine.begin() as conn:
        for stmt in statements:
            await conn.execute(text(stmt))
    await engine.dispose()


async def _fetch(url: str, sql: str):
    engine = create_async_engine(url, poolclass=NullPool)
    async with engine.connect() as conn:
        rows = (await conn.execute(text(sql))).mappings().all()
    await engine.dispose()
    return rows


def _compare(url: str):
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext

    async def _run():
        engine = create_async_engine(url, poolclass=NullPool)
        async with engine.connect() as conn:
            diff = await conn.run_sync(
                lambda sync: compare_metadata(
                    MigrationContext.configure(sync, opts={"compare_type": True, "version_table": "support_alembic_version"}), Base.metadata
                )
            )
        await engine.dispose()
        return diff

    return asyncio.run(_run())


def test_baseline_keeps_existing_data_and_matches_models(support_database):
    from alembic import command

    url = _migration_db_url()
    recreate_database(url)
    asyncio.run(_exec(url, OLD_SCHEMA))

    # Qo'lda `stamp` qilmasdan to'g'ridan-to'g'ri upgrade — baseline mavjud jadvalni taniydi.
    command.upgrade(alembic_config(url), "head")

    rows = asyncio.run(
        _fetch(
            url,
            "SELECT id, user_id, subject, body, status::text AS status, priority::text AS priority, "
            "last_message_at, user_last_read_at, staff_last_read_at FROM support_tickets ORDER BY user_id",
        )
    )
    # Har foydalanuvchiga bitta chat: 42 ning ikki murojaati birlashdi.
    assert [r["user_id"] for r in rows] == [42, 43]
    chat = rows[0]
    assert chat["id"] == 1 and chat["subject"] == "Yordam chati" and chat["body"] == ""
    # Birortasi ochiq — chat ochiq; muhimlik — eng yuqorisi; "closed" endi ishlatilmaydi.
    assert chat["status"] == "open" and chat["priority"] == "high"
    assert rows[1]["status"] == "resolved"
    # last_message_at — oxirgi xabar vaqti, o'qildi belgilari to'ldirilgan.
    assert chat["last_message_at"].isoformat().startswith("2026-01-03T11:00:00")
    assert chat["user_last_read_at"] is not None and chat["staff_last_read_at"] is not None

    # Murojaat matnlari xabarga aylandi, hammasi vaqt tartibida bitta chatda.
    messages = asyncio.run(
        _fetch(url, "SELECT ticket_id, body FROM support_messages ORDER BY ticket_id, created_at, id")
    )
    assert [(m["ticket_id"], m["body"]) for m in messages] == [
        (1, "📌 Eski\nEski murojaat matni"),
        (1, "Eski javob"),
        (1, "📌 Ikkinchi\nYana muammo"),
        (1, "Ikkinchiga izoh"),
        (3, "📌 Haydovchi\nHaydovchi savoli"),
    ]

    # Modellar va migratsiyalar bir xil sxema beradi.
    assert _compare(url) == []

    # Pastga va qayta yuqoriga ham ishlaydi (xabarlar ikki marta qo'shilmaydi).
    command.downgrade(alembic_config(url), "s0001_baseline")
    command.upgrade(alembic_config(url), "head")
    again = asyncio.run(_fetch(url, "SELECT count(*) AS n FROM support_messages"))
    assert again[0]["n"] == 5


def test_fresh_database_matches_models(support_database):
    assert _compare(support_database) == []


# ─── Buyurtma hodisalari ─────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "old, new, expected",
    [
        ("PENDING", "ACCEPTED", "haydovchi qidirilmoqda → haydovchi biriktirildi"),
        ("OrderStatus.IN_PROGRESS", "COMPLETED", "yo'lda → yakunlandi"),
        ("pending", "cancelled", "haydovchi qidirilmoqda → bekor qilindi"),
    ],
)
def test_order_status_labels(old, new, expected):
    text_ = support_main.order_event_text(
        queue.EVENT_ORDER_STATUS_CHANGED, {"order_id": 5, "old_status": old, "new_status": new}
    )
    assert expected in text_


def test_order_status_without_old_value():
    text_ = support_main.order_event_text(
        queue.EVENT_ORDER_STATUS_CHANGED, {"order_id": 5, "old_status": None, "new_status": "PENDING"}
    )
    assert text_ == "Buyurtma #5 holati: haydovchi qidirilmoqda"


@pytest.mark.parametrize(
    "event, data",
    [
        ("order.waypoint_changed", {"order_id": 5, "waypoint_id": 1}),
        ("order.trip_started", {"order_id": 5}),
        ("order.something_new", {"order_id": 5}),
        (queue.EVENT_ORDER_STATUS_CHANGED, {"order_id": 5, "old_status": "ACCEPTED", "new_status": "ACCEPTED"}),
    ],
)
def test_other_order_events_are_ignored(event, data):
    assert support_main.order_event_text(event, data) is None


async def test_order_event_adds_system_note_and_pushes_ws(client, actors):
    actors.order_access[9] = {OWNER}
    actors.order_access[10] = {STRANGER}
    ticket = await new_ticket(client, OWNER, order_id=9)
    other = await new_ticket(client, STRANGER, order_id=10)

    sub = await realtime.get_broker().subscribe([realtime.user_channel(OWNER)])
    await support_main._handle_order_event(
        queue.EVENT_ORDER_STATUS_CHANGED, {"order_id": 9, "old_status": "PENDING", "new_status": "ACCEPTED"}
    )
    event = await sub.get(timeout=1)
    await sub.close()
    assert event["type"] == "message.created"
    assert event["ticket_id"] == ticket["id"]
    assert "haydovchi biriktirildi" in event["message"]["body"]

    detail = (await client.get(f"/support/tickets/{ticket['id']}", headers=auth(OWNER))).json()
    assert detail["messages"][-1]["is_system"] is True
    # Boshqa buyurtma haqidagi chatga tushmaydi.
    other_detail = (await client.get(f"/support/tickets/{other['id']}", headers=auth(STRANGER))).json()
    assert not any(m["is_system"] for m in other_detail["messages"])
    # Tizim izohi foydalanuvchi uchun "o'qilmagan" hisoblanmaydi.
    assert (await client.get("/support/unread", headers=auth(OWNER))).json()["messages"] == 0


# ─── WebSocket ───────────────────────────────────────────────────────────────


@pytest.fixture
def ws_client(db_clean, fake_core, events, monkeypatch):
    from fastapi.testclient import TestClient

    async def _no_queue(_handler):
        raise queue.QueueUnavailable("test")

    monkeypatch.setattr(queue, "consume_order_events", _no_queue)
    with TestClient(support_main.app) as tc:
        yield tc


def test_ws_delivers_new_messages_to_owner_and_staff(ws_client, actors):
    tc = ws_client
    ticket = tc.post(
        "/support/tickets", json={"subject": "WS sinov", "body": "Real vaqt sinovi"}, headers=auth(OWNER)
    ).json()

    with tc.websocket_connect(f"/support/ws?token={make_token(OWNER)}") as owner_ws, tc.websocket_connect(
        f"/support/ws?token={make_token(MANAGER, 'manager')}"
    ) as staff_ws:
        assert owner_ws.receive_json()["type"] == "hello"
        assert staff_ws.receive_json()["type"] == "hello"

        resp = tc.post(
            f"/support/tickets/{ticket['id']}/messages", json={"body": "Javob"}, headers=auth(MANAGER)
        )
        assert resp.status_code == 201

        for ws in (owner_ws, staff_ws):
            event = ws.receive_json()
            assert event["type"] == "message.created"
            assert event["message"]["body"] == "Javob"
            assert event["ticket"]["status"] == "in_progress"

        tc.patch(f"/support/tickets/{ticket['id']}/status", json={"status": "resolved"}, headers=auth(MANAGER))
        assert owner_ws.receive_json()["ticket"]["status"] == "resolved"


def test_ws_send_message_acks_and_reaches_staff(ws_client, actors):
    """Matnli xabar WS orqali: yuboruvchiga `message.ack`, xodimga `message.created`."""
    tc = ws_client
    with tc.websocket_connect(f"/support/ws?token={make_token(OWNER)}") as owner_ws, tc.websocket_connect(
        f"/support/ws?token={make_token(MANAGER, 'manager')}"
    ) as staff_ws:
        assert owner_ws.receive_json()["type"] == "hello"
        assert staff_ws.receive_json()["type"] == "hello"

        owner_ws.send_json({"type": "message.send", "client_id": "c1", "body": "WS orqali salom"})

        # Birinchi xabar chatni yaratadi: xodim ro'yxatiga yangi chat, keyin xabar.
        assert staff_ws.receive_json()["type"] == "ticket.created"
        created = staff_ws.receive_json()
        assert created["type"] == "message.created"
        assert created["message"]["body"] == "WS orqali salom"

        seen = [owner_ws.receive_json() for _ in range(3)]
        types = [e["type"] for e in seen]
        assert sorted(types) == ["message.ack", "message.created", "ticket.created"]
        ack = next(e for e in seen if e["type"] == "message.ack")
        assert ack["client_id"] == "c1"
        assert ack["message"]["body"] == "WS orqali salom"
        assert ack["message"]["ticket"]["status"] == "open"

        # Xodim shu chatga WS orqali javob beradi.
        staff_ws.send_json(
            {"type": "message.send", "client_id": "s1", "body": "Qabul qildik", "ticket_id": ack["message"]["ticket_id"]}
        )
        reply = owner_ws.receive_json()
        assert reply["type"] == "message.created" and reply["message"]["body"] == "Qabul qildik"


def test_ws_send_invalid_message_returns_error(ws_client, actors):
    tc = ws_client
    with tc.websocket_connect(f"/support/ws?token={make_token(OWNER)}") as ws:
        assert ws.receive_json()["type"] == "hello"
        ws.send_json({"type": "message.send", "client_id": "bad", "body": ""})
        error = ws.receive_json()
        assert error == {"type": "message.error", "client_id": "bad", "status": 422, "detail": "Xabar noto'g'ri"}
        # Begona chatga yozib bo'lmaydi (oddiy foydalanuvchi uchun ticket_id — faqat o'ziniki).
        ws.send_json({"type": "message.send", "client_id": "x", "body": "salom", "ticket_id": 999})
        assert ws.receive_json()["status"] == 404


def test_ws_isolated_between_users(ws_client, actors):
    tc = ws_client
    with tc.websocket_connect(f"/support/ws?token={make_token(OWNER)}") as owner_ws:
        assert owner_ws.receive_json()["type"] == "hello"
        tc.portal.call(
            functools.partial(realtime.publish, "message.created", {"ticket_id": 1}, user_id=999, staff=True)
        )
        tc.portal.call(
            functools.partial(realtime.publish, "message.created", {"ticket_id": 2}, user_id=OWNER, staff=False)
        )
        # Begona foydalanuvchi va xodimlar kanali hodisasi kelmaydi — birinchi kelgani o'ziniki.
        assert owner_ws.receive_json()["ticket_id"] == 2


def test_ws_rejects_blocked_user(ws_client, actors):
    from starlette.websockets import WebSocketDisconnect

    actors.user(OWNER, "sender", active=False)
    with pytest.raises(WebSocketDisconnect) as exc:
        with ws_client.websocket_connect(f"/support/ws?token={make_token(OWNER)}") as ws:
            ws.receive_json()
    assert exc.value.code == 4403


def test_ws_rejects_bad_token(ws_client, actors):
    from starlette.websockets import WebSocketDisconnect

    with pytest.raises(WebSocketDisconnect) as exc:
        with ws_client.websocket_connect("/support/ws?token=garbage") as ws:
            ws.receive_json()
    assert exc.value.code == 4401


