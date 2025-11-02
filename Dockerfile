# ============================
# === Stage 1: Build layer ===
# ============================
FROM python:3.11-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DEBIAN_FRONTEND=noninteractive \
    LANG=C.UTF-8

# כלי בנייה מינימליים (לא עוברים ל-Runtime)
RUN apt-get update -y && apt-get install -y --no-install-recommends \
    build-essential curl ca-certificates git \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .

# התקנת תלויות לפייתון למסלול /install (להעתקה ל-Runtime)
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
    WEB_CONCURRENCY=1 \
    GUNICORN_TIMEOUT=180 \
    GUNICORN_GRACEFUL_TIMEOUT=45 \
    GUNICORN_KEEPALIVE=30 \
    GUNICORN_MAX_REQUESTS=500 \
    GUNICORN_MAX_REQUESTS_JITTER=50 \
    LANG=C.UTF-8 \
    MPLCONFIGDIR=/app/.cache/matplotlib

# ===== Runtime OS deps =====
# curl: בדיקות HTTP/HEALTHCHECK
# openssl+xxd: חתימות HMAC/hex
# coreutils/sed/gawk/uuid-runtime: עיבוד/nonce
# tini+tzdata+certs: סביבה תקינה
RUN apt-get update -y && apt-get install -y --no-install-recommends \
    tini ca-certificates tzdata bash curl openssl xxd uuid-runtime sed gawk coreutils git \
    libopenblas0-openmp liblapack3 \
    libfreetype6 libpng16-16 libjpeg62-turbo zlib1g \
 && update-ca-certificates \
 && rm -rf /var/lib/apt/lists/*

# העתקת תלויות פייתון שנבנו בשלב ה-builder
COPY --from=builder /install /usr/local

# הבטחת 'python' מפנה ל-python3 בלבד
RUN set -eux; \
    python3 --version; \
    rm -f /usr/local/bin/python; \
    ln -s "$(which python3)" /usr/local/bin/python; \
    python --version

# יצירת משתמש לא-רוט
RUN useradd -ms /bin/bash appuser
WORKDIR /app

# קוד האפליקציה
COPY . .

# חותמת גרסה (אופציונלי)
RUN printf "%s\n" "${APP_VERSION}" > /app/VERSION || true

# הרשאות ותיקיות עבודה
RUN mkdir -p /app/.cache/matplotlib /app/static/ultra /app/logs /app/data \
 && chown -R appuser:appuser /app

USER appuser

EXPOSE 10000

# Healthcheck פנימי → /readyz
HEALTHCHECK --interval=30s --timeout=10s --retries=5 \
  CMD curl -fsS "http://127.0.0.1:${PORT:-10000}/readyz" || exit 1

# init
ENTRYPOINT ["/usr/bin/tini","--"]

# מודול ה-ASGI
ENV APP_MODULE=main:app

# הרצה עם Gunicorn+UvicornWorker
CMD ["bash","-lc","exec gunicorn -k uvicorn.workers.UvicornWorker \"${APP_MODULE:-main:app}\" --bind 0.0.0.0:${PORT:-10000} --timeout ${GUNICORN_TIMEOUT:-180} --graceful-timeout ${GUNICORN_GRACEFUL_TIMEOUT:-45} --keep-alive ${GUNICORN_KEEPALIVE:-30} --max-requests ${GUNICORN_MAX_REQUESTS:-500} --max-requests-jitter ${GUNICORN_MAX_REQUESTS_JITTER:-50}"]




