"""Og'irlikka qarab narx (truck_types.price_per_ton_km) va waypoint viloyati

- `truck_types.price_per_ton_km` — 1 tonna-km narxi. Mavjud turlar 0 oladi, ya'ni admin
  to'ldirmaguncha narxlar o'zgarmaydi.
- `order_waypoints.region_id` — nuqta qaysi viloyatga tushishi (`services/regions.py`,
  `data/geo/uzbekistan_regional.geojson` id'lari). Jonli xarita filteri uchun.
  Mavjud yozuvlar `scripts/backfill_waypoint_regions.py` bilan to'ldiriladi.

Revision ID: c3d9a1e5f720
Revises: f1a6c2e83d47
Create Date: 2026-11-18

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c3d9a1e5f720"
down_revision: Union[str, Sequence[str], None] = "f1a6c2e83d47"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "truck_types",
        sa.Column("price_per_ton_km", sa.Numeric(12, 2), nullable=False, server_default="0"),
    )
    op.add_column("order_waypoints", sa.Column("region_id", sa.SmallInteger(), nullable=True))
    op.create_index("ix_order_waypoints_region_id", "order_waypoints", ["region_id"])


def downgrade() -> None:
    op.drop_index("ix_order_waypoints_region_id", table_name="order_waypoints")
    op.drop_column("order_waypoints", "region_id")
    op.drop_column("truck_types", "price_per_ton_km")
