"""Add versioned Pricing Engine V2 tariff drafts.

Revision ID: c9e8a1b47f62
Revises: b2f6d3e8a417
"""
from alembic import op
import sqlalchemy as sa

revision = "c9e8a1b47f62"
down_revision = "b2f6d3e8a417"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "pricing_v2_tariffs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("truck_type_id", sa.Integer(), sa.ForeignKey("truck_types.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("profile", sa.JSON(), nullable=False),
        sa.Column("created_by", sa.BigInteger(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("truck_type_id", "version", name="uq_pricing_v2_truck_version"),
        sa.CheckConstraint("status in ('draft', 'published')", name="ck_pricing_v2_tariffs_status"),
    )
    op.create_index("ix_pricing_v2_tariffs_truck_type_id", "pricing_v2_tariffs", ["truck_type_id"])


def downgrade():
    op.drop_index("ix_pricing_v2_tariffs_truck_type_id", table_name="pricing_v2_tariffs")
    op.drop_table("pricing_v2_tariffs")
