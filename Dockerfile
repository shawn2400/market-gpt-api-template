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
    GUNICORN_TIMEOUT=180 \
    GUNICORN_GRACEFUL_TIMEOUT=45 \
    GUNICORN_KEEPALIVE=30 \
    GUNICORN_MAX_REQUESTS=500 \
    GUNICORN_MAX_REQUESTS_JITTER=50 \
    MPLCONFIGDIR=/app/.cache/matplotlib \
    TZ=Asia/Jerusalem \
    DEBIAN_FRONTEND=noninteractive \
    PORT=10000 \
    APP_VERSION=${APP_VERSION} \
    ALGOGPT_VERSION=${APP_VERSION}

RUN apt-get update -y && apt-get install -y --no-install-recommends \
    tini ca-certificates tzdata bash curl git \
    libopenblas0-openmp liblapack3 \
    libfreetype6 libpng16-16 libjpeg62-turbo zlib1g \
 && rm -rf /var/lib/apt/lists/*

# deps from builder
COPY --from=builder /install /usr/local

# non-root user
RUN useradd -ms /bin/bash appuser

WORKDIR /app
COPY . .

# write version file (optional)
RUN printf "%s\n" "${APP_VERSION}" > /app/VERSION || true

# gunicorn config (simple)
RUN [ -f /app/gunicorn_conf.py ] || cat > /app/gunicorn_conf.py <<'PY'
bind = '0.0.0.0:' + str(__import__('os').environ.get('PORT', '10000'))
worker_class = 'uvicorn.workers.UvicornWorker'
accesslog = '-'
errorlog  = '-'
loglevel  = __import__('os').environ.get('UVICORN_LOG_LEVEL','info')
graceful_timeout = int(__import__('os').environ.get('GUNICORN_GRACEFUL_TIMEOUT','45'))
timeout = int(__import__('os').environ.get('GUNICORN_TIMEOUT','180'))
keepalive = int(__import__('os').environ.get('GUNICORN_KEEPALIVE','30'))
workers = int(__import__('os').environ.get('WEB_CONCURRENCY','1'))
PY

# create needed dirs (includes UltraTop static dir to avoid noop)
RUN mkdir -p /app/.cache/matplotlib /app/static /app/static/ultra /app/logs /app/data || true \
 && chown -R appuser:appuser /app

USER appuser

EXPOSE 10000
HEALTHCHECK --interval=30s --timeout=10s --retries=5 \
  CMD curl -fsS http://127.0.0.1:${PORT:-10000}/health || exit 1

ENTRYPOINT ["/usr/bin/tini","--"]
CMD ["gunicorn","-k","uvicorn.workers.UvicornWorker","-c","/app/gunicorn_conf.py","${APP_MODULE:-main:app}"]





























