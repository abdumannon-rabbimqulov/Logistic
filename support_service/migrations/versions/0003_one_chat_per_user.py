"""Har foydalanuvchiga BITTA yordam chati.

Ilgari har muammo uchun alohida murojaat (mavzu + matn) ochilardi. Endi
`support_tickets` qatori — foydalanuvchining yagona suhbati:

1. Har murojaatning mavzusi va matni chatdagi oddiy xabarga aylanadi
   ("📌 Mavzu" + matn, murojaat ochilgan vaqt bilan) — tarix yo'qolmaydi.
2. Bir foydalanuvchining barcha murojaatlari eng eskisiga birlashtiriladi:
   xabarlar (biriktirmalari bilan) unga ko'chadi, qolganlari o'chiriladi.
   - holat: birortasi ochiq bo'lsa — ochiq, ishlanayotgan bo'lsa — ishlanmoqda,
     aks holda hal qilingan; muhimlik — eng yuqorisi;
   - mas'ul xodim va buyurtma — eng so'nggi faol murojaatdan;
   - o'qildi belgilari — eng kichigi (o'qilmagan javob yashirinib qolmasin).
3. "Yopilgan" (closed) holat endi ishlatilmaydi — chat doim ochiq; bunday
   murojaatlar "hal qilingan" ga o'tadi. Enum qiymati eski yozuvlar uchun qoladi.
4. `user_id` — yagona (unique). Xabarlarda yangi `order_id`: qaysi buyurtma
   haqida yozilgani (buyurtma sahifasidan kelinganda).

Xabarlar tartibi endi `created_at, id` bo'yicha (1-qadamdagi xabarlarning id'si
yangi, vaqti esa eski).

Downgrade sxemani qaytaradi, lekin birlashtirilgan murojaatlarni qayta ajratmaydi.

Revision ID: s0003_one_chat
Revises: s0002_unread_attach
Create Date: 2026-11-19
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "s0003_one_chat"
down_revision: Union[str, Sequence[str], None] = "s0002_unread_attach"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

CHAT_SUBJECT = "Yordam chati"


def upgrade() -> None:
    op.add_column("support_messages", sa.Column("order_id", sa.Integer(), nullable=True))

    # 1. Murojaat mavzusi va matni → xabar.
    op.execute(
        """
        INSERT INTO support_messages
            (ticket_id, author_user_id, author_role, author_name, is_system, body, created_at, order_id)
        SELECT id, user_id, user_role, user_name, false,
               '📌 ' || subject || CASE WHEN body <> '' THEN E'\\n' || body ELSE '' END,
               created_at, order_id
        FROM support_tickets
        -- Faqat haqiqiy murojaat matni (birlashtirilgan chatda body bo'sh — qayta
        -- upgrade qilinganda ham ikkinchi marta qo'shilmaydi).
        WHERE body <> ''
        """
    )

    # 2. Har foydalanuvchi uchun yig'ma qiymatlar → eng eski murojaatga.
    op.execute(
        """
        WITH ranked AS (
            SELECT t.*,
                   row_number() OVER (PARTITION BY user_id ORDER BY last_message_at DESC, id DESC) AS rn
            FROM support_tickets t
        ),
        latest AS (SELECT * FROM ranked WHERE rn = 1),
        agg AS (
            SELECT user_id,
                   min(id) AS keep_id,
                   bool_or(status = 'open') AS any_open,
                   bool_or(status = 'in_progress') AS any_progress,
                   max(CASE priority WHEN 'urgent' THEN 4 WHEN 'high' THEN 3
                                     WHEN 'normal' THEN 2 ELSE 1 END) AS prio,
                   max(last_message_at) AS last_at,
                   min(user_last_read_at) AS user_read,
                   min(staff_last_read_at) AS staff_read,
                   bool_or(staff_last_read_at IS NULL) AS staff_never_read
            FROM support_tickets
            GROUP BY user_id
        )
        UPDATE support_tickets t
        SET status = (CASE WHEN a.any_open THEN 'open'
                           WHEN a.any_progress THEN 'in_progress'
                           ELSE 'resolved' END)::ticketstatus,
            priority = (CASE a.prio WHEN 4 THEN 'urgent' WHEN 3 THEN 'high'
                                    WHEN 2 THEN 'normal' ELSE 'low' END)::ticketpriority,
            last_message_at = a.last_at,
            user_last_read_at = a.user_read,
            staff_last_read_at = CASE WHEN a.staff_never_read THEN NULL ELSE a.staff_read END,
            assigned_to = l.assigned_to,
            assigned_name = l.assigned_name,
            order_id = l.order_id,
            user_role = l.user_role,
            user_name = l.user_name,
            subject = :subject,
            body = ''
        FROM agg a, latest l
        WHERE t.id = a.keep_id AND l.user_id = a.user_id
        """.replace(":subject", f"'{CHAT_SUBJECT}'")
    )

    # 3. Qolgan murojaatlarning xabarlari asosiy chatga, keyin ular o'chiriladi.
    op.execute(
        """
        WITH keep AS (SELECT user_id, min(id) AS keep_id FROM support_tickets GROUP BY user_id)
        UPDATE support_messages m
        SET ticket_id = k.keep_id
        FROM support_tickets t
        JOIN keep k ON k.user_id = t.user_id
        WHERE m.ticket_id = t.id AND t.id <> k.keep_id
        """
    )
    op.execute(
        """
        DELETE FROM support_tickets t
        USING (SELECT user_id, min(id) AS keep_id FROM support_tickets GROUP BY user_id) k
        WHERE t.user_id = k.user_id AND t.id <> k.keep_id
        """
    )

    # 4. Indekslar: bitta foydalanuvchi — bitta chat; xabarlar vaqt bo'yicha.
    op.drop_index("ix_support_tickets_user_id", table_name="support_tickets")
    op.create_index("ix_support_tickets_user_id", "support_tickets", ["user_id"], unique=True)
    op.create_index(
        "ix_support_messages_ticket_created",
        "support_messages",
        ["ticket_id", "created_at", "id"],
    )


def downgrade() -> None:
    op.drop_index("ix_support_messages_ticket_created", table_name="support_messages")
    op.drop_index("ix_support_tickets_user_id", table_name="support_tickets")
    op.create_index("ix_support_tickets_user_id", "support_tickets", ["user_id"])
    op.drop_column("support_messages", "order_id")
