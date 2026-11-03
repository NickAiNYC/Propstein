FROM python:3.12-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    APP_ENV=production \
    ENVIRONMENT=production \
    LOG_LEVEL=INFO \
    PYTHONPATH=/app:/app/src
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN useradd --create-home --uid 10001 propstein \
    && mkdir -p /data \
    && chown -R propstein:propstein /app /data
USER propstein
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
  CMD python -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:' + os.environ.get('PORT','8000') + '/health', timeout=4)" || exit 1
CMD ["sh", "-c", "if [ \"$SERVICE_ROLE\" = \"worker\" ]; then exec python scripts/live_nba_sniper_worker.py; else exec uvicorn api.main:app --host 0.0.0.0 --port ${PORT:-8000}; fi"]
