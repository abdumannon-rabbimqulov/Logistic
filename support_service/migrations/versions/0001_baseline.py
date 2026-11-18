"""Baseline: avvalgi `Base.metadata.create_all` yaratgan sxema.

Ishlab chiqarishdagi `support_db` da jadvallar allaqachon bor (xizmat ilgari
startda `create_all` qilardi). Shuning uchun bu revizion jadval MAVJUD bo'lsa
hech narsa qilmaydi — faqat alembic versiyasini qayd etadi. Bo'sh bazada esa
o'sha sxemaning aynan o'zini yaratadi. Natijada `alembic upgrade head` ikkala
holatda ham qo'lda `stamp` qilmasdan ishlaydi va mavjud ma'lumot buzilmaydi.

Revision ID: s0001_baseline
Revises:
Create Date: 2026-11-18
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "s0001_baseline"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

ticket_status = postgresql.ENUM(
    "open", "in_progress", "resolved", "closed", name="ticketstatus", create_type=False
)
ticket_priority = postgresql.ENUM(
    "low", "normal", "high", "urgent", name="ticketpriority", create_type=False
)


def upgrade() -> None:
    bind = op.get_bind()
    if sa.inspect(bind).has_table("support_tickets"):
        return  # mavjud baza — baseline sifatida qabul qilinadi

    ticket_status.create(bind, checkfirst=True)
    ticket_priority.create(bind, checkfirst=True)

    op.create_table(
        "support_tickets",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("user_role", sa.String(length=20), nullable=True),
        sa.Column("order_id", sa.Integer(), nullable=True),
        sa.Column("subject", sa.String(length=200), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("status", ticket_status, nullable=False),
        sa.Column("priority", ticket_priority, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_support_tickets_user_id", "support_tickets", ["user_id"])
    op.create_index("ix_support_tickets_order_id", "support_tickets", ["order_id"])
    op.create_index("ix_support_tickets_status", "support_tickets", ["status"])

    op.create_table(
        "support_messages",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "ticket_id",
            sa.Integer(),
            sa.ForeignKey("support_tickets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("author_user_id", sa.BigInteger(), nullable=True),
        sa.Column("author_role", sa.String(length=20), nullable=True),
        sa.Column("is_system", sa.Boolean(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_support_messages_ticket_id", "support_messages", ["ticket_id"])


def downgrade() -> None:
    op.drop_table("support_messages")
    op.drop_table("support_tickets")
    ticket_priority.drop(op.get_bind(), checkfirst=True)
    ticket_status.drop(op.get_bind(), checkfirst=True)
