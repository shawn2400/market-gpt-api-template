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
    ALGOGPT_VERSION=${APP_VERSION} \
    ENABLE_STARTUP_SELF_CHECK=1

# ספריות זמן־ריצה נחוצות
RUN apt-get update -y && apt-get install -y --no-install-recommends \
    bash curl tini ca-certificates tzdata git \
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
# העתקת קוד האפליקציה
COPY . .

# === algo_helpers (לשימוש אינטראקטיבי) ===
RUN cat > /app/algo_helpers.sh <<'SH'
#!/usr/bin/env sh
set -eu
API="${API_BASE:-http://127.0.0.1:${PORT:-10000}}"
AUTH_HEADER=""
[ -n "${API_BEARER_TOKEN:-}" ] && AUTH_HEADER="Authorization: Bearer ${API_BEARER_TOKEN}"
_red() { printf "\033[31m%s\033[0m\n" "$*" >&2; }
_ylw() { printf "\033[33m%s\033[0m\n" "$*"; }
healthz() { curl -fsS "$API/readyz" && echo "OK" || { _red "not ready"; return 1; }; }
version() { curl -fsS "$API/meta/version" || true; }
SH
RUN chmod +x /app/algo_helpers.sh

# כתיבת גרסה לקובץ (fallback ל-/meta/version)
RUN printf "%s\n" "${APP_VERSION}" > /app/VERSION || true

# === gunicorn_conf.py ===
RUN [ -f /app/gunicorn_conf.py ] || cat > /app/gunicorn_conf.py <<'PY'
bind = '0.0.0.0:' + str(__import__('os').environ.get('PORT', '10000'))
worker_class = 'uvicorn.workers.UvicornWorker'
accesslog = '-'
errorlog  = '-'
loglevel  = __import__('os').environ.get('UVICORN_LOG_LEVEL','info')
graceful_timeout = int(__import__('os').environ.get('GUNICORN_GRACEFUL_TIMEOUT','30'))
timeout = int(__import__('os').environ.get('GUNICORN_TIMEOUT','120'))
keepalive = int(__import__('os').environ.get('GUNICORN_KEEPALIVE','5'))
PY

# === prestart.sh ===
RUN [ -f /app/prestart.sh ] || cat > /app/prestart.sh <<'SH'
#!/usr/bin/env sh
set -e
echo "[prestart] warming up..."
mkdir -p /app/.cache/matplotlib /app/logs /app/data || true
SH
RUN chmod +x /app/prestart.sh

# === health_full.sh ===
RUN [ -f /app/health_full.sh ] || cat > /app/health_full.sh <<'SH'
#!/usr/bin/env sh
set -e
curl -fsS "http://127.0.0.1:${PORT:-10000}/readyz" >/dev/null
SH
RUN chmod +x /app/health_full.sh

# הרשאות ותיקיות
RUN mkdir -p /app/static /app/logs /app/data /app/.cache \
 && chmod 755 /app/static /app/logs /app/.cache /app/data || true \
 && chown -R appuser:appuser /app \
 && (find /usr/local /app -type d -name '__pycache__' -prune -exec rm -rf {} + 2>/dev/null || true)

# טעינת ההלפרים לסשן של המשתמש
RUN printf "%s\n" 'if [ -f /app/algo_helpers.sh ]; then . /app/algo_helpers.sh; fi' >> /home/appuser/.profile \
 && chown appuser:appuser /home/appuser/.profile

USER appuser

HEALTHCHECK --interval=30s --timeout=10s --retries=5 \
  CMD ["/bin/sh","-lc","/app/health_full.sh || curl -fsS http://127.0.0.1:${PORT:-10000}/readyz || exit 1"]

EXPOSE 10000

# שימוש ב-tini ליציבות סיגנלים וזומבים
ENTRYPOINT ["/usr/bin/tini","--"]

# CMD מריץ:
# 1) prestart
# 2) Gate אתחול (אם ENABLE_STARTUP_SELF_CHECK=1). אם המודול לא קיים — מדלגים; אם קיים ונכשל — Exit 23.
# 3) gunicorn
CMD ["/bin/sh","-lc","\
  /app/prestart.sh 2>/dev/null || true; \
  if [ \"${ENABLE_STARTUP_SELF_CHECK:-1}\" = \"1\" ]; then \
    python - <<'PY' || exit 23; \
try: \
    import importlib, os, sys; \
    mod = importlib.import_module('app.scripts.startup_gate'); \
    ok = mod.main() if hasattr(mod,'main') else True; \
    sys.exit(0 if ok else 23) \
except ModuleNotFoundError: \
    print('[startup-gate] module not found, skipping (set ENABLE_STARTUP_SELF_CHECK=0 to silence)'); \
    sys.exit(0) \
PY \
  fi; \
  exec gunicorn ${APP_MODULE:-main:app} -c gunicorn_conf.py \
    --workers ${WEB_CONCURRENCY:-1} \
    --bind 0.0.0.0:${PORT:-10000} \
    --timeout ${GUNICORN_TIMEOUT:-120} \
    --graceful-timeout ${GUNICORN_GRACEFUL_TIMEOUT:-30} \
    --keep-alive ${GUNICORN_KEEPALIVE:-5} \
    --max-requests ${GUNICORN_MAX_REQUESTS:-500} \
    --max-requests-jitter ${GUNICORN_MAX_REQUESTS_JITTER:-50} \
    --worker-class uvicorn.workers.UvicornWorker \
"]






































