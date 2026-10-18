FROM python:3.12-slim

WORKDIR /app
COPY . /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/app IOT_DB_PATH=/data/industrial_iot.db
RUN mkdir -p /data
EXPOSE 8080
CMD ["python", "-m", "backend.http_api"]
