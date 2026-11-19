"""Support mikroservizi testlari uchun muhit.

Haqiqiy PostgreSQL kerak (`SELECT ... FOR UPDATE`, `IS DISTINCT FROM`, enum'lar):
standart — lokal `postgresql+asyncpg://localhost/support_test`, boshqasini
`SUPPORT_TEST_DB_URL` bilan bering. Baza har sessiyada qaytadan yaratiladi va
sxema ALEMBIC orqali quriladi (migratsiyalar ham shu bilan sinaladi). Postgres
topilmasa testlar o'tkazib yuboriladi.

Core API va RabbitMQ almashtiriladi: core — `FakeCore` (foydalanuvchi holati va
buyurtma egalari lug'ati), RabbitMQ — hodisalar ro'yxatga yoziladi. Redis o'rniga
xotira varianti (`REDIS_URL=""`).
"""

from __future__ import annotations

import asyncio
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

import pytest

TEST_DB_URL = os.environ.get(
    "SUPPORT_TEST_DB_URL", "postgresql+asyncpg://localhost/support_test"
)
_UPLOAD_ROOT = tempfile.mkdtemp(prefix="support-uploads-")

# `support_service.config` import paytida o'qiydi — shuning uchun eng boshida.
os.environ["SUPPORT_DB_URL"] = TEST_DB_URL
os.environ.setdefault("SECRET_KEY", "support-test-secret")
os.environ["REDIS_URL"] = ""
os.environ["SUPPORT_UPLOAD_DIR"] = _UPLOAD_ROOT
os.environ["SUPPORT_DB_NULLPOOL"] = "1"
os.environ["CORE_API_URL"] = "http://core.invalid/api"

asyncpg = pytest.importorskip("asyncpg")
pytest.importorskip("httpx")
pytest.importorskip("alembic")

from jose import jwt  # noqa: E402

from support_service import config as support_config  # noqa: E402
from support_service import core_client, kv, queue, realtime, storage  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_INI = ROOT / "support_service" / "alembic.ini"


def _dsn(url: str, database: Optional[str] = None) -> tuple[str, str]:
    """SQLAlchemy URL → (asyncpg DSN, baza nomi)."""
    from sqlalchemy.engine import make_url

    parsed = make_url(url)
    name = parsed.database
    plain = parsed.set(drivername="postgresql", database=database or name)
    return plain.render_as_string(hide_password=False), name


async def _recreate_database(url: str) -> None:
    admin_dsn, name = _dsn(url, "postgres")
    conn = await asyncpg.connect(admin_dsn, timeout=5)
    try:
        await conn.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            "WHERE datname = $1 AND pid <> pg_backend_pid()",
            name,
        )
        await conn.execute(f'DROP DATABASE IF EXISTS "{name}"')
        await conn.execute(f'CREATE DATABASE "{name}"')
    finally:
        await conn.close()


def alembic_config(url: str):
    from alembic.config import Config

    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option("sqlalchemy.url", url)
    cfg.attributes["configure_logger"] = False
    return cfg


def recreate_database(url: str) -> None:
    try:
        asyncio.run(_recreate_database(url))
    except (OSError, asyncpg.PostgresError, asyncio.TimeoutError) as exc:
        pytest.skip(f"Support testlari uchun PostgreSQL mavjud emas ({url}): {exc}")


@pytest.fixture(scope="session")
def support_database() -> str:
    from alembic import command

    recreate_database(TEST_DB_URL)
    command.upgrade(alembic_config(TEST_DB_URL), "head")
    return TEST_DB_URL


# ─── Soxta core ──────────────────────────────────────────────────────────────


class FakeCore:
    def __init__(self) -> None:
        self.users: dict[int, core_client.UserStatus] = {}
        self.order_access: dict[int, set[int]] = {}
        self.available = True
        self.status_calls = 0

    def user(self, user_id: int, role: str = "sender", name: Optional[str] = None, active: bool = True):
        self.users[user_id] = core_client.UserStatus(
            active=active, role=role, full_name=name or f"User {user_id}"
        )

    async def fetch_user_status(self, token: str) -> core_client.UserStatus:
        self.status_calls += 1
        if not self.available:
            raise core_client.CoreUnavailable("core down")
        payload = jwt.get_unverified_claims(token)
        user_id = int(payload["sub"])
        if user_id not in self.users:
            raise core_client.CoreUnauthorized("unknown")
        return self.users[user_id]

    async def user_can_access_order(self, token: str, order_id: int) -> bool:
        if not self.available:
            raise core_client.CoreUnavailable("core down")
        user_id = int(jwt.get_unverified_claims(token)["sub"])
        status = self.users.get(user_id)
        if status is not None and status.role in support_config.STAFF_ROLES:
            return True
        return user_id in self.order_access.get(order_id, set())


@pytest.fixture
def fake_core(monkeypatch) -> FakeCore:
    fake = FakeCore()
    monkeypatch.setattr(core_client, "fetch_user_status", fake.fetch_user_status)
    monkeypatch.setattr(core_client, "user_can_access_order", fake.user_can_access_order)
    return fake


@pytest.fixture
def events(monkeypatch) -> list[tuple[str, dict[str, Any]]]:
    published: list[tuple[str, dict[str, Any]]] = []

    async def _publish(event: str, payload: dict[str, Any]) -> bool:
        published.append((event, payload))
        return True

    monkeypatch.setattr(queue, "publish_event", _publish)
    return published


def make_token(user_id: int, role: Optional[str] = "sender", *, token_type: str = "access") -> str:
    payload = {
        "sub": str(user_id),
        "role": role,
        "type": token_type,
        "exp": datetime.now(timezone.utc) + timedelta(minutes=30),
    }
    return jwt.encode(payload, support_config.SECRET_KEY, algorithm=support_config.ALGORITHM)


def auth(user_id: int, role: Optional[str] = "sender") -> dict[str, str]:
    return {"Authorization": f"Bearer {make_token(user_id, role)}"}


@pytest.fixture
async def db_clean(support_database):
    """Har test oldidan jadvallarni tozalaydi va xotira holatini yangilaydi."""
    from sqlalchemy import text

    from support_service.db import engine

    async with engine.begin() as conn:
        await conn.execute(
            text("TRUNCATE support_attachments, support_messages, support_tickets RESTART IDENTITY CASCADE")
        )
    kv.set_kv(kv.MemoryKV())
    realtime.set_broker(realtime.MemoryBroker())
    storage.set_storage(storage.LocalStorage(_UPLOAD_ROOT))
    yield
    await engine.dispose()


@pytest.fixture
async def client(db_clean, fake_core, events):
    import httpx

    from support_service.main import app

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        yield http


# Standart aktyorlar: 1001 — mijoz, 1002 — boshqa mijoz, 2001 — menejer, 3001 — admin.
OWNER, STRANGER, MANAGER, ADMIN = 1001, 1002, 2001, 3001


@pytest.fixture
def actors(fake_core: FakeCore) -> FakeCore:
    fake_core.user(OWNER, "sender", "Ali Valiyev")
    fake_core.user(STRANGER, "sender", "Begona")
    fake_core.user(MANAGER, "manager", "Menejer Madina")
    fake_core.user(ADMIN, "admin", "Admin Aziz")
    return fake_core


async def new_ticket(http, user_id: int = OWNER, **extra) -> dict[str, Any]:
    body = {"subject": "Haydovchi kelmadi", "body": "Soat 10 da kelishi kerak edi", **extra}
    resp = await http.post("/support/tickets", json=body, headers=auth(user_id))
    assert resp.status_code == 201, resp.text
    return resp.json()
