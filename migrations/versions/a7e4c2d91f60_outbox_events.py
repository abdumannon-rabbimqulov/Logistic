"""Transactional outbox jadvali (outbox_events)

Biznes hodisalari (order.status_changed va h.k.) endi o'zgarish bilan bitta
tranzaksiyada shu jadvalga yoziladi va events-worker ularni RabbitMQ'ga yuboradi
(`services/outbox.py`).

Revision ID: a7e4c2d91f60
Revises: c3d9a1e5f720
Create Date: 2026-11-19

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "a7e4c2d91f60"
down_revision: Union[str, Sequence[str], None] = "c3d9a1e5f720"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Web ilovaning `create_all` i jadvalni migratsiyadan oldin yaratib qo'ygan bo'lishi
    # mumkin (dev muhitida) — shunda faqat indeks tekshiriladi.
    if sa.inspect(op.get_bind()).has_table("outbox_events"):
        op.create_index(
            "ix_outbox_events_unpublished",
            "outbox_events",
            ["id"],
            postgresql_where=sa.text("published_at IS NULL"),
            if_not_exists=True,
        )
        return
    op.create_table(
        "outbox_events",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("event_id", sa.String(36), nullable=False, unique=True),
        sa.Column("event", sa.String(64), nullable=False),
        sa.Column("envelope", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempts", sa.SmallInteger(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text(), nullable=True),
    )
    op.create_index(
        "ix_outbox_events_unpublished",
        "outbox_events",
        ["id"],
        postgresql_where=sa.text("published_at IS NULL"),
        if_not_exists=True,
    )


def downgrade() -> None:
    op.drop_index("ix_outbox_events_unpublished", table_name="outbox_events")
    op.drop_table("outbox_events")
