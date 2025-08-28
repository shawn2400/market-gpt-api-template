#!/usr/bin/env bash
set -Eeuo pipefail

# ──────────────────────────────────────────────
# Clean Binance Keys (remove quotes / CR / LF / tabs / spaces)
# ──────────────────────────────────────────────
export BINANCE_API_KEY="$(printf '%s' "${BINANCE_API_KEY:-}" | sed 's/^"//; s/"$//' | tr -d '\r\n\t ')"
export BINANCE_API_SECRET="$(printf '%s' "${BINANCE_API_SECRET:-}" | sed 's/^"//; s/"$//' | tr -d '\r\n\t ')"

# ──────────────────────────────────────────────
# Verify lengths (Binance keys must be 64 chars)
# ──────────────────────────────────────────────
echo "[prestart] KEY=${#BINANCE_API_KEY}, SECRET=${#BINANCE_API_SECRET}"

if [ ${#BINANCE_API_KEY} -ne 64 ]; then
  echo "[prestart][FATAL] API_KEY length ${#BINANCE_API_KEY} != 64"
  exit 10
fi

if [ ${#BINANCE_API_SECRET} -ne 64 ]; then
  echo "[prestart][FATAL] API_SECRET length ${#BINANCE_API_SECRET} != 64"
  exit 11
fi

echo "[prestart] Binance keys sanitized and valid (64/64)."
