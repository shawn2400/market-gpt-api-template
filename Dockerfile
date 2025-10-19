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

# יצירת algo_helpers.sh בבילד (ללא jq) + הרשאות
RUN set -eu; cat > /app/algo_helpers.sh <<'SH'
#!/usr/bin/env sh
# Utility helpers (no jq)

set -eu

API="${API_BASE:-http://127.0.0.1:${PORT:-10000}}"
AUTH=""
[ -n "${API_BEARER_TOKEN:-}" ] && AUTH="Authorization: Bearer ${API_BEARER_TOKEN}"

_red() { printf "\033[31m%s\033[0m\n" "$*" >&2; }
_grn() { printf "\033[32m%s\033[0m\n" "$*"; }
_ylw() { printf "\033[33m%s\033[0m\n" "$*"; }

algoinfo() {
  echo "API: $API"
  echo "PORT: ${PORT:-10000}"
  echo "TZ: ${TZ:-}"
  echo "APP_VERSION: ${ALGOGPT_VERSION:-}"
  echo "HAS_TOKEN: $( [ -n "${API_BEARER_TOKEN:-}" ] && echo yes || echo no )"
  echo -n "READYZ: "; curl -fsS "$API/readyz" 2>/dev/null || echo "fail"
}

healthz() { curl -fsS "$API/readyz" && echo "OK" || { _red "not ready"; return 1; }; }

version() { curl -fsS "$API/meta/version" || true; }

# mk_ticket SYMBOL SIDE QTY LEV [NOTE]
mk_ticket() {
  sym="${1:-}"; side="${2:-}"; qty="${3:-}"; lev="${4:-}"; note="${5:-}"
  [ -z "$sym" ]  && { _red "missing symbol"; return 2; }
  [ -z "$side" ] && { _red "missing side"; return 2; }
  [ -z "$qty" ]  && { _red "missing qty"; return 2; }
  [ -z "$lev" ]  && { _red "missing leverage"; return 2; }
  esc() { printf '%s' "$1" | sed 's/\\/\\\\/g; s/"/\\"/g'; }
  note_esc="$(esc "${note:-}")"
  json=$(printf '{"symbol":"%s","side":"%s","qty":%s,"leverage":%s,"note":"%s"}' \
        "$sym" "$side" "$qty" "$lev" "$note_esc")
  _ylw "POST /ops/ticket  $json"
  curl -fsS -H "Content-Type: application/json" -d "$json" "$API/ops/ticket" || { _red "ticket create failed"; return 1; }
  echo
}

approve_ticket() { tid="${1:-}"; [ -z "$tid" ] && { _red "usage: approve_ticket <ticket_id>"; return 2; }; curl -fsS -H "$AUTH" "$API/ops/approve?ticket_id=$tid" || { _red "approve failed"; return 1; }; echo; }
reject_ticket()  { tid="${1:-}"; [ -z "$tid" ] && { _red "usage: reject_ticket <ticket_id>"; return 2; };  curl -fsS -H "$AUTH" "$API/ops/reject?ticket_id=$tid"  || { _red "reject failed";  return 1; }; echo; }

# manage-once SYMBOL [offset_bps] [pcts_csv] [splits_csv]
manage_once() {
  sym="${1:-}"; [ -z "$sym" ] && { _red "usage: manage_once <SYMBOL> [offset_bps] [pcts_csv] [splits_csv]"; return 2; }
  off="${2:-}"; pcts="${3:-}"; splits="${4:-}"
  body='{"symbol":"'"$sym"'"'
  [ -n "$off" ]    && body="$body,\"offset_bps\":$off"
  [ -n "$pcts" ]   && body="$body,\"pcts\":[${pcts}]"
  [ -n "$splits" ] && body="$body,\"splits\":[${splits}]"
  body="$body}"
  _ylw "POST /manage-once  $body"
  curl -fsS -H "$AUTH" -H "Content-Type: application/json" -d "$body" "$API/manage-once" || { _red "manage failed"; return 1; }
  echo
}

hc() { curl -fsS -H "$AUTH" "$@"; }
SH
RUN chmod +x /app/algo_helpers.sh

# כתיבת גרסה לקובץ (fallback ל-/meta/version)
RUN printf "%s\n" "${APP_VERSION}" > /app/VERSION || true

# קבצי ברירת־מחדל שנחוצים ל־CMD
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

# טעינה אוטומטית של ההלפרים לכל סשן shell של appuser
RUN printf "%s\n" "\
# === Algo helpers auto-load ===\n\
if [ -f /app/algo_helpers.sh ]; then\n\
  . /app/algo_helpers.sh\n\
fi\n" >> /home/appuser/.bashrc \
 && printf "%s\n" "\
# === Algo helpers auto-load ===\n\
if [ -f /app/algo_helpers.sh ]; then\n\
  . /app/algo_helpers.sh\n\
fi\n" >> /home/appuser/.profile \
 && chown appuser:appuser /home/appuser/.bashrc /home/appuser/.profile

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





































