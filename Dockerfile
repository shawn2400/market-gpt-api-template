# ============================
# === Stage 1: Build layer ===
# ============================
FROM python:3.11-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DEBIAN_FRONTEND=noninteractive

RUN apt-get update -y && apt-get install -y --no-install-recommends \
    build-essential curl ca-certificates git \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .

RUN python -m pip install --upgrade pip setuptools wheel \
 && pip install --prefix=/install --no-cache-dir --upgrade-strategy eager -r requirements.txt \
 && pip check

# ================================
# === Stage 2: Runtime layer  ====
# ================================
FROM python:3.11-slim

ARG APP_VERSION=2.18.0
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONOPTIMIZE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONPATH=/app \
    APP_MODULE=main:app \
    WEB_CONCURRENCY=1 \
    GUNICORN_TIMEOUT=120 \
    GUNICORN_GRACEFUL_TIMEOUT=30 \
    GUNICORN_KEEPALIVE=5 \
    GUNICORN_MAX_REQUESTS=500 \
    GUNICORN_MAX_REQUESTS_JITTER=50 \
    MPLCONFIGDIR=/app/.cache/matplotlib \
    TZ=Asia/Jerusalem \
    DEBIAN_FRONTEND=noninteractive \
    PORT=10000 \
    APP_VERSION=${APP_VERSION} \
    ALGOGPT_VERSION=${APP_VERSION}

# ספריות זמן־ריצה נחוצות (OpenBLAS/PNG/JPEG למספריות מדעיות ו־matplotlib)
RUN apt-get update -y && apt-get install -y --no-install-recommends \
    curl tini ca-certificates tzdata git \
    libopenblas0-openmp liblapack3 \
    libfreetype6 libpng16-16 libjpeg62-turbo zlib1g \
    procps psmisc \
    openssl vim-common \
 && rm -rf /var/lib/apt/lists/*

# התקנת התלויות מהשכבה הראשונה
COPY --from=builder /install /usr/local

# משתמש לא-root
RUN useradd -ms /bin/bash appuser

WORKDIR /app
COPY . .

# כתיבת גרסה לקובץ (fallback ל-/meta/version)
RUN printf "%s\n" "${APP_VERSION}" > /app/VERSION || true

# קבצים משלימים שה־CMD משתמש בהם (אם לא הועתקו ע״י COPY לעיל)
# (ניצור ברירת־מחדל בטוחה כדי למנוע שגיאה אם חסר)
RUN test -f /app/gunicorn_conf.py || printf "%s\n" "\
bind = '0.0.0.0:' + str(__import__('os').environ.get('PORT', '10000'))\n\
worker_class = 'uvicorn.workers.UvicornWorker'\n\
accesslog = '-'\n\
errorlog  = '-'\n\
loglevel  = __import__('os').environ.get('UVICORN_LOG_LEVEL','info')\n\
graceful_timeout = int(__import__('os').environ.get('GUNICORN_GRACEFUL_TIMEOUT','30'))\n\
timeout = int(__import__('os').environ.get('GUNICORN_TIMEOUT','120'))\n\
keepalive = int(__import__('os').environ.get('GUNICORN_KEEPALIVE','5'))\n" > /app/gunicorn_conf.py

RUN test -f /app/prestart.sh || printf "%s\n" "\
#!/usr/bin/env sh\n\
set -e\n\
echo \"[prestart] warming up...\"\n\
mkdir -p /app/.cache/matplotlib /app/logs /app/data || true\n\
" > /app/prestart.sh && chmod +x /app/prestart.sh

RUN test -f /app/health_full.sh || printf "%s\n" "\
#!/usr/bin/env sh\n\
set -e\n\
curl -fsS http://127.0.0.1:${PORT:-10000}/readyz >/dev/null\n\
" > /app/health_full.sh && chmod +x /app/health_full.sh

# הרשאות ותיקיות
RUN mkdir -p /app/static /app/logs /app/data /app/.cache \
 && chmod 755 /app/static /app/logs /app/.cache /app/data || true \
 && chown -R appuser:appuser /app \
 && (find /usr/local /app -type d -name '__pycache__' -prune -exec rm -rf {} + 2>/dev/null || true)

USER appuser

HEALTHCHECK --interval=30s --timeout=10s --retries=5 \
  CMD ["/bin/sh","-c","/app/health_full.sh || curl -fsS http://127.0.0.1:${PORT:-10000}/readyz || exit 1"]

EXPOSE 10000

ENTRYPOINT ["/usr/bin/tini", "--"]

# הערה: כל משתני הסביבה מוזנים מה־Render, לא קשה-מקודד כאן.
CMD ["/bin/sh","-lc","/app/prestart.sh 2>/dev/null || true; \
  gunicorn ${APP_MODULE} -c gunicorn_conf.py \
    --workers ${WEB_CONCURRENCY:-1} \
    --bind 0.0.0.0:${PORT:-10000} \
    --timeout ${GUNICORN_TIMEOUT:-120} \
    --graceful-timeout ${GUNICORN_GRACEFUL_TIMEOUT:-30} \
    --keep-alive ${GUNICORN_KEEPALIVE:-5} \
    --max-requests ${GUNICORN_MAX_REQUESTS:-500} \
    --max-requests-jitter ${GUNICORN_MAX_REQUESTS_JITTER:-50} \
    --worker-class uvicorn.workers.UvicornWorker"]







































