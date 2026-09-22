FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    SITE_DIR=/app/site \
    SEMINAR_DATA_DIR=/data \
    SEMINAR_INBOX_DIR=/inbox \
    PRESENTER_MAP_PATH=/config/presenter-map.json \
    PORT=8000

WORKDIR /app
COPY site/ /app/site/
COPY seminar_service/app.py /app/seminar_service/app.py
COPY teams_sync/app.py /app/teams_sync/app.py
COPY teams_sync/device_login.py /app/teams_sync/device_login.py

RUN chmod -R a=rX /app/site /app/seminar_service /app/teams_sync \
    && useradd --system --uid 10001 --create-home ailab \
    && mkdir -p /data/items /inbox /config \
    && chown -R ailab:ailab /data /inbox /config

USER ailab
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=2)"

CMD ["python", "/app/seminar_service/app.py"]
