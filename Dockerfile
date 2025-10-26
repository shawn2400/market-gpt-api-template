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

# install deps into /install to copy later
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
    TZ=Asia/Jerusalem \
    DEBIAN_FRONTEND=noninteractive \
    PORT=10000 \
    APP_VERSION=${APP_VERSION} \
    ALGOGPT_VERSION=${APP_VERSION} \
    # Gunicorn defaults (ניתן לשנות ב-ENV של Render)
    WEB_CONCURRENCY=1 \
    GUNICORN_TIMEOUT=180 \
    GUNICORN_GRACEFUL_TIMEOUT=45 \
    GUNICORN_KEEPALIVE=30 \
    GUNICORN_MAX_REQUESTS=500 \
    GUNICORN_MAX_REQUESTS_JITTER=50

# packages needed at runtime
RUN apt-get update -y && apt-get install -y --no-install-recommends \
    tini ca-certificates tzdata bash curl openssl xxd uuid-runtime sed gawk coreutils git \
    libopenblas0-openmp liblapack3 \
    libfreetype6 libpng16-16 libjpeg62-turbo zlib1g \
 && rm -rf /var/lib/apt/lists/*

# copy python deps from builder
COPY --from=builder /install /usr/local

# non-root user
RUN useradd -ms /bin/bash appuser

WORKDIR /app

# app code
COPY . .

# version stamp (optional)
RUN printf "%s\n" "${APP_VERSION}" > /app/VERSION || true

# dirs + permissions
RUN mkdir -p /app/.cache/matplotlib /app/static/ultra /app/logs /app/data \
 && chown -R appuser:appuser /app

USER appuser

EXPOSE 10000

# in-container healthcheck → /readyz (כמו בהגדרות Render)
HEALTHCHECK --interval=30s --timeout=10s --retries=5 \
  CMD curl -fsS http://127.0.0.1:${PORT:-10000}/readyz || exit 1

# keep init
ENTRYPOINT ["/usr/bin/tini","--"]

# מודול ה-ASGI
ENV APP_MODULE=main:app

# הרצה נקייה עם Gunicorn+UvicornWorker; שימוש ב-bash כדי לאפשר הרחבת ENV (PORT וכו')
CMD ["bash","-lc", "exec gunicorn -k uvicorn.workers.UvicornWorker \"${APP_MODULE:-main:app}\" --bind 0.0.0.0:${PORT:-10000} --timeout ${GUNICORN_TIMEOUT:-180} --graceful-timeout ${GUNICORN_GRACEFUL_TIMEOUT:-45} --keep-alive ${GUNICORN_KEEPALIVE:-30} --max-requests ${GUNICORN_MAX_REQUESTS:-500} --max-requests-jitter ${GUNICORN_MAX_REQUESTS_JITTER:-50}"]










