# Chat mikroservizining o'z image'i (support_service/Dockerfile naqshi).
#
# Build konteksti — loyiha ildizi, lekin ichiga FAQAT `chat_service/` ko'chiriladi:
# asosiy kodga bog'liqlik bo'lsa konteynerda darhol ImportError bilan ko'rinadi.

FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    libjpeg62-turbo-dev \
    zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*

COPY chat_service/requirements.txt ./chat_service/requirements.txt
RUN pip install --no-cache-dir -r chat_service/requirements.txt

# Servislararo shartnoma — yagona manba.
COPY contracts/ ./contracts/
COPY chat_service/ ./chat_service/

# Media volume'i shu yerga ulanadi (docker-compose: chat_media).
RUN mkdir -p /app/uploads/chat

EXPOSE 8000

# Migratsiya har startda (idempotent) — alohida `migrate` konteyneri kerak emas,
# chunki chat bazasini faqat shu xizmat ishlatadi.
CMD ["sh", "-c", "alembic -c chat_service/alembic.ini upgrade head && exec uvicorn chat_service.main:app --host 0.0.0.0 --port 8000 --proxy-headers"]
