"""O'qilmaganlar, biriktirish, muallif nomi va fayl biriktirmalari.

- support_tickets: user_name, assigned_to/assigned_name, user_last_read_at,
  staff_last_read_at, last_message_at (+ indeks)
- support_messages: author_name
- support_attachments (yangi jadval) + attachmentkind enum

Mavjud murojaatlar uchun `last_message_at` oxirgi xabar vaqtidan to'ldiriladi,
o'qildi belgilari esa "hozir" qilinadi — migratsiyadan keyin hamma eski
murojaat birdan "o'qilmagan" bo'lib chiqmasin.

Revision ID: s0002_unread_attach
Revises: s0001_baseline
Create Date: 2026-11-18
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "s0002_unread_attach"
down_revision: Union[str, Sequence[str], None] = "s0001_baseline"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

attachment_kind = postgresql.ENUM("image", "video", "document", name="attachmentkind", create_type=False)


def upgrade() -> None:
    op.add_column("support_tickets", sa.Column("user_name", sa.String(length=128), nullable=True))
    op.add_column("support_tickets", sa.Column("assigned_to", sa.BigInteger(), nullable=True))
    op.add_column("support_tickets", sa.Column("assigned_name", sa.String(length=128), nullable=True))
    op.add_column(
        "support_tickets", sa.Column("user_last_read_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "support_tickets", sa.Column("staff_last_read_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "support_tickets",
        sa.Column(
            "last_message_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.execute(
        """
        UPDATE support_tickets t SET
            last_message_at = COALESCE(
                (SELECT MAX(m.created_at) FROM support_messages m WHERE m.ticket_id = t.id),
                t.created_at
            ),
            user_last_read_at = now(),
            staff_last_read_at = now()
        """
    )
    op.create_index("ix_support_tickets_assigned_to", "support_tickets", ["assigned_to"])
    op.create_index("ix_support_tickets_last_message_at", "support_tickets", ["last_message_at"])

    op.add_column("support_messages", sa.Column("author_name", sa.String(length=128), nullable=True))

    attachment_kind.create(op.get_bind(), checkfirst=True)
    op.create_table(
        "support_attachments",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "message_id",
            sa.Integer(),
            sa.ForeignKey("support_messages.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("storage_key", sa.String(length=255), nullable=False, unique=True),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("content_type", sa.String(length=100), nullable=False),
        sa.Column("kind", attachment_kind, nullable=False),
        sa.Column("size", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_support_attachments_message_id", "support_attachments", ["message_id"])


def downgrade() -> None:
    op.drop_table("support_attachments")
    attachment_kind.drop(op.get_bind(), checkfirst=True)
    op.drop_column("support_messages", "author_name")
    op.drop_index("ix_support_tickets_last_message_at", table_name="support_tickets")
    op.drop_index("ix_support_tickets_assigned_to", table_name="support_tickets")
    for column in (
        "last_message_at",
        "staff_last_read_at",
        "user_last_read_at",
        "assigned_name",
        "assigned_to",
        "user_name",
    ):
        op.drop_column("support_tickets", column)
