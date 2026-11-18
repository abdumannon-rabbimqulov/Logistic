"""Haydovchi "Start" bosgan vaqt (orders.started_at)

Har bir buyurtma haydovchining "Start" tugmasi bilan boshlanadi (yuk olish
nuqtasiga yo'lga chiqdi). Hozir yo'lda bo'lgan buyurtmalar to'xtab qolmasligi
uchun ACCEPTED/IN_PROGRESS buyurtmalarga migratsiya vaqti yoziladi.

Revision ID: b2f6d3e8a417
Revises: a7e4c2d91f60
Create Date: 2026-11-19

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "b2f6d3e8a417"
down_revision: Union[str, Sequence[str], None] = "a7e4c2d91f60"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("orders", sa.Column("started_at", sa.DateTime(timezone=True), nullable=True))
    op.execute(
        "UPDATE orders SET started_at = now() "
        "WHERE status IN ('ACCEPTED', 'IN_PROGRESS') AND started_at IS NULL"
    )


def downgrade() -> None:
    op.drop_column("orders", "started_at")
