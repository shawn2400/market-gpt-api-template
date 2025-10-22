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

# התקנה בשכבת build (ל-prefix /install כדי להעביר לשכבת הריצה)
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
    ALGOGPT_VERSION=${APP_VERSION} \
    HTTP2_ENABLE=1

# ספריות ריצה הנדרשות ל־numpy/scipy/matplotlib/Pillow ועוד
RUN apt-get update -y && apt-get install -y --no-install-recommends \
    tini ca-certificates tzdata bash curl git \
    libopenblas0-openmp liblapack3 \
    libfreetype6 libpng16-16 libjpeg62-turbo zlib1g \
 && rm -rf /var/lib/apt/lists/*

# תלויות מפאזה 1
COPY --from=builder /install /usr/local

# משתמש לא־רוט
RUN useradd -ms /bin/bash appuser

WORKDIR /app

# העתקת קוד האפליקציה (כולל gunicorn_conf.py אם קיים ברפוזיטורי)
COPY . .

# גרסת אפליקציה לשקיפות
RUN printf "%s\n" "${APP_VERSION}" > /app/VERSION || true

# תיקיות והרשאות
RUN mkdir -p /app/.cache/matplotlib /app/static/ultra /app/logs /app/data \
 && chown -R appuser:appuser /app

USER appuser

EXPOSE 10000

# בריאות בתוך הקונטיינר – תואם לנתיב /readyz
HEALTHCHECK --interval=30s --timeout=10s --retries=5 \
  CMD curl -fsS http://127.0.0.1:${PORT:-10000}/readyz || exit 1

ENTRYPOINT ["/usr/bin/tini","--"]
CMD ["gunicorn","-c","/app/gunicorn_conf.py"]



























