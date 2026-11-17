"""Tezlik uchun indekslar: orders, order_waypoints, users.phone_number

Bu ustunlar bo'yicha har so'rovda qidiriladi, lekin indeks yo'q edi — Postgres
butun jadvalni o'qirdi (seq scan):

  orders(customer_id, created_at)   GET /orders (yuboruvchi ro'yxati)
  orders(driver_id, created_at)     GET /orders (haydovchi ro'yxati), dispatch
  orders(status, created_at)        /orders/available/list, admin filtrlari, dashboard
  order_waypoints(order_id)         har bir buyurtma bilan nuqtalarni yuklash (selectinload)
  users(phone_number)               POST /auth/login (telefon+parol)

`IF NOT EXISTS` — `create_all` bilan yaratilgan yangi bazada indekslar allaqachon
bo'lishi mumkin (modellarda ham e'lon qilingan).

Revision ID: f1a6c2e83d47
Revises: d8e3b6c04f27
Create Date: 2026-11-17

"""
from typing import Sequence, Union

from alembic import op


revision: str = "f1a6c2e83d47"
down_revision: Union[str, Sequence[str], None] = "d8e3b6c04f27"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


INDEXES = {
    "ix_orders_customer_created": "orders (customer_id, created_at)",
    "ix_orders_driver_created": "orders (driver_id, created_at)",
    "ix_orders_status_created": "orders (status, created_at)",
    "ix_order_waypoints_order_id": "order_waypoints (order_id)",
    "ix_users_phone_number": "users (phone_number)",
}


def upgrade() -> None:
    for name, target in INDEXES.items():
        op.execute(f"CREATE INDEX IF NOT EXISTS {name} ON {target}")


def downgrade() -> None:
    for name in INDEXES:
        op.execute(f"DROP INDEX IF EXISTS {name}")
