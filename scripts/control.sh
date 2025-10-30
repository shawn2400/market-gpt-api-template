#!/usr/bin/env bash
set -euo pipefail
BASE="${BASE:-https://<your-render-app>.onrender.com}"
BEARER="${API_BEARER_TOKEN:?set API_BEARER_TOKEN in Replit secrets}"

call() {
  local path="$1"; local method="${2:-GET}"; local body="${3:-}"
  if [ "$method" = "POST" ]; then
    curl -fsS -X POST "$BASE$path" \
      -H "Authorization: Bearer $BEARER" \
      -H "Content-Type: application/json" \
      --data "$body"
  else
    curl -fsS -X GET "$BASE$path" \
      -H "Authorization: Bearer $BEARER"
  fi
  echo
}
