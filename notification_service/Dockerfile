# Notification mikroservizi — faqat `notification_service/` ko'chiriladi, shuning uchun
# asosiy kodni import qilish urinishi konteynerda darhol ImportError beradi.
FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

COPY notification_service/requirements.txt ./notification_service/requirements.txt
RUN pip install --no-cache-dir -r notification_service/requirements.txt

COPY notification_service/ ./notification_service/

CMD ["python", "-m", "notification_service.main"]
