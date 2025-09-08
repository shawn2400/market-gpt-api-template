# ============================
# === Stage 1: Build layer ===
# ============================
FROM python:3.11-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update -y && apt-get install -y --no-install-recommends \
    build-essential curl ca-certificates \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .

RUN python -m pip install --upgrade pip setuptools wheel \
 && pip install --prefix=/install --no-cache-dir --upgrade-strategy eager -r requirements.txt \
 && pip check

# ================================
# === Stage 2: Runtime layer =====
# ================================
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=10000 \
    WEB_CONCURRENCY=1 \
    GUNICORN_TIMEOUT=120 \
    PYTHONPATH=/app \
    APP_MODULE=main:app

RUN apt-get update -y && apt-get install -y --no-install-recommends \
    curl tini ca-certificates \
    libopenblas0-openmp liblapack3 \
    libfreetype6 libpng16-16 libjpeg62-turbo zlib1g \
    procps psmisc \
 && rm -rf /var/lib/apt/lists/*

# ספריות מה-builder
COPY --from=builder /install /usr/local

# משתמש לא-שורש
RUN useradd -ms /bin/bash appuser

# קוד האפליקציה
WORKDIR /app
COPY . .

# תיקיות בסיס + ניקוי __pycache__ בלי לגעת ב-/proc
RUN mkdir -p /app/static /app/logs /app/data /app/.cache \
 && chmod 755 /app/static /app/logs /app/.cache /app/data || true \
 && chown -R appuser:appuser /app \
 && (find /usr/local /app -type d -name '__pycache__' -prune -exec rm -rf {} + 2>/dev/null || true)

# prestart & health
RUN test -f /app/prestart.sh && chmod +x /app/prestart.sh || true \
 && test -f /app/health_full.sh && chmod +x /app/health_full.sh || true

USER appuser

# בריאות
HEALTHCHECK --interval=30s --timeout=10s --retries=5 \
  CMD ["/bin/sh", "-c", "[ -x /app/health_full.sh ] && /app/health_full.sh || curl -fsS http://127.0.0.1:${PORT}/health || exit 1"]

ENTRYPOINT ["/usr/bin/tini", "--"]

# Gunicorn + Uvicorn — ברירת מחדל main:app; אפשר להחליף ל-app_single:app עם APP_MODULE
CMD bash -lc " \
  bash /app/prestart.sh 2>/dev/null || true && \
  gunicorn ${APP_MODULE} \
    --workers ${WEB_CONCURRENCY:-1} \
    --bind 0.0.0.0:${PORT:-10000} \
    --timeout ${GUNICORN_TIMEOUT:-120} \
    --worker-class uvicorn.workers.UvicornWorker"






























