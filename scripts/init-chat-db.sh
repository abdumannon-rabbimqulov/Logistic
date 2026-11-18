#!/bin/bash
# Chat mikroservizi uchun alohida baza yaratadi (`init-support-db.sh` naqshi).
#
# Postgres `/docker-entrypoint-initdb.d/` dagi skriptlarni FAQAT bo'sh ma'lumot
# katalogida (birinchi ishga tushishda) bajaradi. Bazasi allaqachon bor loyihada:
#
#   docker compose exec db psql -U postgres -c "CREATE DATABASE chat_db"
#
# (yoki `make chat-db-create`). Jadvallarni chat konteynerining o'zi alembic bilan
# yaratadi (chat_service/Dockerfile CMD).
set -e

CHAT_DB_NAME="${CHAT_DB_NAME:-chat_db}"

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    SELECT 'CREATE DATABASE $CHAT_DB_NAME'
    WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = '$CHAT_DB_NAME')\gexec
EOSQL

echo "init-chat-db: '$CHAT_DB_NAME' bazasi tayyor"
