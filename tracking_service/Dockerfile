# Tracking mikroservizi — faqat `tracking_service/` ko'chiriladi (asosiy kodni import
# qilish urinishi konteynerda darhol ImportError beradi).
FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

COPY tracking_service/requirements.txt ./tracking_service/requirements.txt
RUN pip install --no-cache-dir -r tracking_service/requirements.txt

COPY tracking_service/ ./tracking_service/

EXPOSE 8000

CMD ["uvicorn", "tracking_service.main:app", "--host", "0.0.0.0", "--port", "8000", "--ws-ping-interval", "20"]
