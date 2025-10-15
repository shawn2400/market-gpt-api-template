#!/usr/bin/env bash
# ------------------------------------------------------------
# Hit public feed endpoints (with optional bearer)
# שימוש:
#   bash scripts/hit_public_feed.sh "<BASE_URL>" "<PUBLIC_BEARER (optional)>"
# הערות:
#   - תואם ל־PUBLIC_REQUIRE_BEARER=1 (אם מופעל — חייבים טוקן)
#   - מכסה: /scan/public-topk, /scan/public-now, /topk, /topk.csv, ו־SSE ticket (דוגמית קצרה)
#   - שופרו הודעות שגיאה/סטטוס ל-curl. ללא jq.
# ------------------------------------------------------------
set -Eeuo pipefail

BASE_URL="${1:-http://127.0.0.1:10000}"
PUBLIC_BEARER="${2:-${API_BEARER_TOKEN:-}}"

# הגדרות זמן/ריטריי ניתנות לשינוי דרך ENV
CURL_CONNECT_TIMEOUT="${CURL_CONNECT_TIMEOUT:-5}"
CURL_MAX_TIME="${CURL_MAX_TIME:-12}"
CURL_RETRY="${CURL_RETRY:-2}"
CURL_RETRY_DELAY="${CURL_RETRY_DELAY:-1}"

# צבעים (רק אם למסך יש TTY)
if [[ -t 1 ]]; then
  G=$'\033[0;32m'; R=$'\033[0;31m'; Y=$'\033[1;33m'; B=$'\033[0;34m'; N=$'\033[0m'
else
  G=''; R=''; Y=''; B=''; N=''
fi
ok(){   printf "%sOK%s   - %s\n"   "$G" "$N" "$1"; }
warn(){ printf "%sWARN%s - %s\n" "$Y" "$N" "$1"; }
fail(){ printf "%sFAIL%s - %s\n" "$R" "$N" "$1"; exit 1; }

# כותרת Authorization אם יש טוקן
_auth=()
[[ -n "$PUBLIC_BEARER" ]] && _auth=(-H "Authorization: Bearer ${PUBLIC_BEARER}")

printf "%s=== 🌐 Public feed: %s ===%s\n" "$B" "$BASE_URL" "$N"

# ---------- עזר: תרגום קוד יציאה של curl ----------
explain_curl_exit() {
  local code="${1:-0}"
  case "$code" in
    0)   echo "ok" ;;
    3)   echo "Malformed URL" ;;
    5)   echo "Proxy resolution failure" ;;
    6)   echo "Could not resolve host (DNS)" ;;
    7)   echo "Failed to connect (refused/timeout)" ;;
    18)  echo "Transfer closed with outstanding data" ;;
    28)  echo "Operation timeout" ;;
    35)  echo "SSL connect error" ;;
    47)  echo "Too many redirects" ;;
    51)  echo "SSL: host name mismatch" ;;
    52)  echo "Empty reply from server" ;;
    56)  echo "Failure in receiving network data" ;;
    60)  echo "SSL certificate problem" ;;
    77)  echo "Problem with SSL CA cert path" ;;
    92)  echo "HTTP/2 framing layer error" ;;
    *)   echo "curl exit ${code}" ;;
  esac
}

# ---------- עזר: הדפסת כמה שורות ראשונות ----------
print_head() {
  local text="$1"
  local lines="${2:-20}"
  # הסרת רווחי התחלה להצגה נקייה
  printf "%s\n\n" "$(printf "%s" "$text" | sed -e 's/^[[:space:]]*//' | head -n "$lines")"
}

# ---------- עזר: בקשת GET עם curl (ללא jq) ----------
# שימוש: get_endpoint "<URL>" "<ACCEPT>" "<PREVIEW_LINES>"
# מחזיר דרך משתנים גלובליים:
#   _HTTP_CODE, _BODY, _CURL_EXIT
get_endpoint() {
  local url="$1"
  local accept="${2:-*/*}"
  local preview="${3:-20}"

  # הפעלת curl עם מדדי זמן/ריטריי. לא משתמשים ב-mktemp כדי למנוע בעיות תאימות.
  local out http_code
  set +e
  out="$(
    curl -sS "${_auth[@]}" \
      -H "Accept: ${accept}" \
      --connect-timeout "${CURL_CONNECT_TIMEOUT}" \
      --max-time "${CURL_MAX_TIME}" \
      --retry "${CURL_RETRY}" \
      --retry-delay "${CURL_RETRY_DELAY}" \
      -w $'\n%{http_code}' \
      "$url"
  )"
  _CURL_EXIT=$?
  set -e

  # פיצול אחרון לשורת קוד ה-HTTP
  http_code="${out##*$'\n'}"
  _HTTP_CODE="${http_code}"
  _BODY="${out%$'\n'$http_code}"

  # תצוגה
  if [[ "${_CURL_EXIT}" -ne 0 ]]; then
    warn "$(basename "$url") failed: $(explain_curl_exit "${_CURL_EXIT}")"
    return 0
  fi

  case "${_HTTP_CODE}" in
    200|201|202|203|204)
      ok "$url"
      print_head "${_BODY}" "${preview}"
      ;;
    301|302|307|308)
      warn "$url redirected (${_HTTP_CODE})"
      ;;
    401|403)
      warn "$url unauthorized (PUBLIC_REQUIRE_BEARER=1?)"
      ;;
    404)
      warn "$url not found (404)"
      ;;
    405)
      warn "$url method not allowed (405)"
      ;;
    429)
      warn "$url rate limited (429)"
      ;;
    500|502|503|504)
      warn "$url server error (${_HTTP_CODE})"
      ;;
    *)
      warn "$url unexpected status (${_HTTP_CODE})"
      ;;
  esac
}

# ---------- JSON endpoints ----------
for path in "/scan/public-topk" "/scan/public-now" "/topk"; do
  get_endpoint "${BASE_URL}${path}" "application/json" 20
done

# ---------- CSV ----------
get_endpoint "${BASE_URL}/topk.csv" "text/csv" 10

# ---------- SSE (דוגמית ~5s) ----------
sse_sample() {
  local url="${BASE_URL}/public/sse-ticket"
  local preview_lines=10

  # אם יש timeout במערכת נשתמש בו; אחרת נסמוך על --max-time
  if command -v timeout >/dev/null 2>&1; then
    set +e
    # -N/--no-buffer כדי להזרים שורות בזמן אמת ככל האפשר
    local out
    out="$(timeout 5s curl -fsS "${_auth[@]}" -N --no-buffer "$url" | head -n "${preview_lines}")"
    local rc=$?
    set -e
    if [[ $rc -eq 0 && -n "$out" ]]; then
      ok "/public/sse-ticket (sample)"
      printf "%s\n\n" "$out"
      return 0
    fi
  fi

  # ניסיון נוסף מוגבל בזמן
  set +e
  local out2
  out2="$(curl -fsS "${_auth[@]}" -N --no-buffer --max-time 5 "$url" | head -n "${preview_lines}")"
  local rc2=$?
  set -e
  if [[ $rc2 -eq 0 && -n "$out2" ]]; then
    ok "/public/sse-ticket (sample)"
    printf "%s\n\n" "$out2"
  else
    # אם אין גוף — ננסה להביא רק את הקוד כדי לדעת אם זה הרשאות
    local code
    code="$(curl -s -o /dev/null -w "%{http_code}" "${_auth[@]}" "$url" || true)"
    if [[ "$code" == "401" || "$code" == "403" ]]; then
      warn "/public/sse-ticket unauthorized"
    else
      warn "/public/sse-ticket failed (maybe blocked or no events)"
    fi
  fi
}

sse_sample

printf "%sDONE%s\n" "$G" "$N"

