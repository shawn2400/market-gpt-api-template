#!/usr/bin/env sh
set -eu

echo "[prestart] $(date -u +"%Y-%m-%dT%H:%M:%SZ") starting..."
echo "[prestart] python: $(python -V 2>&1 || true)"
echo "[prestart] app version: ${APP_VERSION:-unknown}"

# ניקוי מפתחות Binance (ללא CR/LF/רווחים/גרשיים)
export BINANCE_API_KEY="$(printf '%s' "${BINANCE_API_KEY:-}" | sed 's/^"//; s/"$//' | tr -d '\r\n\t ')"
export BINANCE_API_SECRET="$(printf '%s' "${BINANCE_API_SECRET:-}" | sed 's/^"//; s/"$//' | tr -d '\r\n\t ')"

STRICT="${PRESTART_STRICT_KEYS:-1}"
echo "[prestart] STRICT_KEYS=${STRICT}  KEY_LEN=${#BINANCE_API_KEY}, SECRET_LEN=${#BINANCE_API_SECRET}"

if [ "${STRICT}" = "1" ]; then
  if [ "${#BINANCE_API_KEY}" -ne 64 ]; then
    echo "[prestart][FATAL] API_KEY length ${#BINANCE_API_KEY} != 64"; exit 10
  fi
  if [ "${#BINANCE_API_SECRET}" -ne 64 ]; then
    echo "[prestart][FATAL] API_SECRET length ${#BINANCE_API_SECRET} != 64"; exit 11
  fi
  echo "[prestart] Binance keys sanitized and valid (64/64)."
else
  if [ -z "${BINANCE_API_KEY:-}" ] || [ -z "${BINANCE_API_SECRET:-}" ]; then
    echo "[prestart][WARN] Binance keys missing; STRICT=0 (skipping length check)"
  fi
fi

# תיקיות והרשאות
mkdir -p /app/data /app/logs /app/.cache || true
chmod 755 /app/data /app/logs /app/.cache || true

# קבצי policy (מידע בלבד)
if [ -n "${POLICY_DSL_PATH:-}" ] && [ -f "${POLICY_DSL_PATH}" ]; then
  echo "[prestart] policy file: ${POLICY_DSL_PATH}"
else
  echo "[prestart] WARNING: policy file missing: ${POLICY_DSL_PATH:-not-set}"
fi

# Env sanity
for k in PORT APP_MODULE PYTHONPATH; do
  v="$(printenv "$k" || true)"
  echo "[prestart] env ${k}=${v:-<empty>}"
done

# בדיקת DNS (לא חוסם)
python - <<'PY'
import socket
for host in ("fapi.binance.com","api.binance.com"):
    try:
        socket.gethostbyname(host)
        print(f"[prestart] DNS OK: {host}")
    except Exception as e:
        print(f"[prestart] DNS FAIL: {host} - {e}")
PY

echo "[prestart] done."

