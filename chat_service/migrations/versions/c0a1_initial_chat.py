"""chat: conversations, media, messages, read_marks

Revision ID: c0a1_initial_chat
Revises:
Create Date: 2026-11-18
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c0a1_initial_chat"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

BigIntPK = sa.BigInteger().with_variant(sa.Integer(), "sqlite")
TS = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "conversations",
        sa.Column("id", BigIntPK, primary_key=True, autoincrement=True),
        sa.Column("order_id", sa.BigInteger(), nullable=False),
        sa.Column("sender_user_id", sa.BigInteger(), nullable=False),
        sa.Column("driver_id", sa.BigInteger(), nullable=True),
        sa.Column("driver_user_id", sa.BigInteger(), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="open"),
        sa.Column("order_status", sa.String(32), nullable=True),
        sa.Column("readonly_at", TS, nullable=True),
        sa.Column("last_event_at", TS, nullable=True),
        sa.Column("last_message_at", TS, nullable=True),
        sa.Column("created_at", TS, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", TS, nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("order_id", name="uq_conversations_order_id"),
    )
    op.create_index("ix_conversations_sender_user_id", "conversations", ["sender_user_id"])
    op.create_index("ix_conversations_driver_user_id", "conversations", ["driver_user_id"])

    op.create_table(
        "media",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column(
            "conversation_id",
            BigIntPK,
            sa.ForeignKey("conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("uploader_user_id", sa.BigInteger(), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("mime", sa.String(64), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("storage_key", sa.String(255), nullable=False),
        sa.Column("thumb_key", sa.String(255), nullable=True),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("duration_s", sa.Float(), nullable=True),
        sa.Column("original_name", sa.String(255), nullable=True),
        sa.Column("created_at", TS, nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_media_conversation_id", "media", ["conversation_id"])

    op.create_table(
        "messages",
        sa.Column("id", BigIntPK, primary_key=True, autoincrement=True),
        sa.Column(
            "conversation_id",
            BigIntPK,
            sa.ForeignKey("conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("sender_user_id", sa.BigInteger(), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("text", sa.Text(), nullable=True),
        sa.Column("media_id", sa.String(32), sa.ForeignKey("media.id", ondelete="SET NULL"), nullable=True),
        sa.Column("duration_s", sa.Float(), nullable=True),
        sa.Column("lat", sa.Float(), nullable=True),
        sa.Column("lon", sa.Float(), nullable=True),
        sa.Column("reply_to_id", BigIntPK, sa.ForeignKey("messages.id", ondelete="SET NULL"), nullable=True),
        sa.Column("client_id", sa.String(64), nullable=True),
        sa.Column("created_at", TS, nullable=False, server_default=sa.func.now()),
        sa.Column("edited_at", TS, nullable=True),
        sa.Column("deleted_at", TS, nullable=True),
        sa.Column("updated_at", TS, nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("media_id", name="uq_messages_media_id"),
        sa.UniqueConstraint("conversation_id", "sender_user_id", "client_id", name="uq_messages_client_id"),
    )
    op.create_index("ix_messages_conversation_id_id", "messages", ["conversation_id", "id"])
    op.create_index("ix_messages_updated_at", "messages", ["updated_at"])

    op.create_table(
        "read_marks",
        sa.Column(
            "conversation_id",
            BigIntPK,
            sa.ForeignKey("conversations.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("user_id", sa.BigInteger(), primary_key=True),
        sa.Column("last_read_message_id", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("updated_at", TS, nullable=False, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("read_marks")
    op.drop_table("messages")
    op.drop_table("media")
    op.drop_table("conversations")
