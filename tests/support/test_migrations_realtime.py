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

from .conftest import MANAGER, OWNER, TEST_DB_URL, alembic_config, auth, make_token, new_ticket, recreate_database

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
        _fetch(url, "SELECT id, subject, last_message_at, user_last_read_at, staff_last_read_at FROM support_tickets")
    )
    assert len(rows) == 1
    assert rows[0]["subject"] == "Eski"
    # last_message_at — oxirgi xabar vaqti, o'qildi belgilari to'ldirilgan.
    assert rows[0]["last_message_at"].isoformat().startswith("2026-01-02T10:00:00")
    assert rows[0]["user_last_read_at"] is not None and rows[0]["staff_last_read_at"] is not None

    # Modellar va migratsiyalar bir xil sxema beradi.
    assert _compare(url) == []

    # Pastga va qayta yuqoriga ham ishlaydi.
    command.downgrade(alembic_config(url), "s0001_baseline")
    command.upgrade(alembic_config(url), "head")


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


async def test_order_event_adds_system_note_and_pushes_ws(client, actors):
    actors.order_access[9] = {OWNER}
    ticket = await new_ticket(client, OWNER, order_id=9)
    closed = await new_ticket(client, OWNER, order_id=9)
    await client.patch(f"/support/tickets/{closed['id']}/status", json={"status": "closed"}, headers=auth(OWNER))

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
    closed_detail = (await client.get(f"/support/tickets/{closed['id']}", headers=auth(OWNER))).json()
    assert closed_detail["messages"] == []
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

        tc.patch(f"/support/tickets/{ticket['id']}/status", json={"status": "closed"}, headers=auth(OWNER))
        assert owner_ws.receive_json()["ticket"]["status"] == "closed"


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


