# utils/binance_client.py
import os
import time
import random
import logging
import requests
from typing import Optional

from dotenv import load_dotenv
load_dotenv(override=False)

from binance.client import Client
from binance.exceptions import BinanceAPIException, BinanceRequestException

# === טעינת קונפיג/ENV ===
try:
    from utils import config
    _API_KEY = (config.BINANCE_API_KEY or "").strip()
    _API_SECRET = (config.BINANCE_API_SECRET or "").strip()
    _BACKOFF_BASE = float(getattr(config, "BINANCE_BACKOFF_BASE", 0.7))
    _MAX_RETRIES = int(getattr(config, "BINANCE_MAX_RETRIES", 5))
    _EX_INFO_ON_START = bool(getattr(config, "BINANCE_EXCHANGE_INFO_ON_START", False))
    _SPOT_HTTP = getattr(config, "BINANCE_SPOT_HTTP_BASE", "https://api.binance.com").strip()
    _FAPI_HTTP = getattr(config, "BINANCE_FUTURES_HTTP_BASE", "https://fapi.binance.com").strip()
except Exception:
    _API_KEY = (os.getenv("BINANCE_API_KEY") or "").strip()
    _API_SECRET = (os.getenv("BINANCE_API_SECRET") or "").strip()
    _BACKOFF_BASE = float(os.getenv("BINANCE_BACKOFF_BASE", "0.7"))
    _MAX_RETRIES = int(os.getenv("BINANCE_MAX_RETRIES", "5"))
    _EX_INFO_ON_START = (os.getenv("BINANCE_EXCHANGE_INFO_ON_START", "false").lower() == "true")
    _SPOT_HTTP = os.getenv("BINANCE_SPOT_HTTP_BASE", "https://api.binance.com").strip()
    _FAPI_HTTP = os.getenv("BINANCE_FUTURES_HTTP_BASE", "https://fapi.binance.com").strip()

# === סשן HTTP גלובלי ידידותי ל-WAF ===
_session = requests.Session()
_session.trust_env = False  # אל תשתמש ב-HTTP(S)_PROXY מהסביבה – מונע חסימות CloudFront
_session.headers.update({
    # UA “דפדפן” סטנדרטי כדי להימנע מטריגרים של WAF/CloudFront
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
    "Accept-Encoding": "gzip",
    "Accept-Language": "en-US,en;q=0.9",
})
# שים לב: לא מוסיפים כאן X-MBX-APIKEY גלובלית כדי לא “להדליק” WAF על קריאות פומביות.
# ה-SDK יוסיף את הכותרת איפה שצריך (קריאות חתומות).

_requests_params = {"timeout": 10}
_client: Optional[Client] = None

def _make_client() -> Client:
    if _API_KEY and _API_SECRET:
        logging.info("[Binance] 🔑 נמצאו מפתחות – מנסה להתחבר…")
        c = Client(_API_KEY, _API_SECRET, tld="com", requests_params=_requests_params)
    else:
        logging.warning("[Binance] ללא מפתחות – מצב Public-Only (klines/market data).")
        c = Client(None, None, tld="com", requests_params=_requests_params)

    # בסיסים עדכניים
    c.API_URL = _SPOT_HTTP
    c.FUTURES_URL = _FAPI_HTTP

    # שימוש בסשן שלנו (UA/timeout/trust_env)
    c.session = _session
    return c

def sync_server_time() -> None:
    """
    סנכרון זמן עם שרת Binance Futures ומדידת offset לרתימת python-binance.
    מפחית false 403/401 הקשורים ל-Timestamp/recvWindow.
    """
    # אם עוד אין לקוח, נייצר זמני
    c = _client or _make_client()
    url = f"{_FAPI_HTTP}/fapi/v1/time"
    t0 = int(time.time() * 1000)
    r = _session.get(url, timeout=5)
    r.raise_for_status()
    server_ms = int(r.json()["serverTime"])
    t1 = int(time.time() * 1000)
    rtt = (t1 - t0)
    estimated_now = t0 + rtt // 2
    offset_ms = server_ms - estimated_now
    c.timestamp_offset = offset_ms  # תכונה קיימת ב-python-binance
    logging.info(f"[Binance] 🕒 time sync: offset={offset_ms}ms rtt~{rtt}ms")

    # אם הלקוח הגלובלי כבר קיים – עדכן אותו; אחרת נציב כעת
    global _client
    _client = c

def get_client() -> Client:
    global _client
    if _client is None:
        _client = _make_client()
        try:
            sync_server_time()
        except Exception as e:
            logging.warning(f"[Binance] ⚠️ sync_server_time נכשל: {e} – נמשיך בכל מקרה.")
    return _client

def _retry_call(fn, *, name: str):
    """קריאה עם ריטריי אקספוננציאלי + ג'יטר; טיפול ב-403/429/CloudFront."""
    last_exc = None
    for attempt in range(_MAX_RETRIES + 1):
        try:
            return fn()
        except BinanceAPIException as e:
            txt = f"http={getattr(e, 'status_code', '?')} code={getattr(e, 'code', '?')} msg={getattr(e, 'message', '')}"
            if e.status_code in (401, 403, 404, 418, 429, 500, 502, 503, 504) or \
               "CloudFront" in str(e) or "Invalid JSON error message" in str(e):
                delay = _BACKOFF_BASE * (2 ** attempt) + random.uniform(0, 0.35)
                logging.warning(f"[Binance] API {name} (attempt {attempt+1}/{_MAX_RETRIES+1}) → {delay:.2f}s ({txt})")
                # ניסיון חד-פעמי לרענון סנכרון זמן בתחילת כשלי 401/403
                if attempt == 0 and (e.status_code in (401, 403) or "Timestamp" in e.message):
                    try:
                        sync_server_time()
                    except Exception:
                        pass
                time.sleep(delay); last_exc = e; continue
            logging.error(f"[Binance] API error in {name}: {txt}")
            raise
        except (BinanceRequestException, requests.exceptions.RequestException) as e:
            delay = _BACKOFF_BASE * (2 ** attempt) + random.uniform(0, 0.35)
            logging.warning(f"[Binance] Network {name} (attempt {attempt+1}/{_MAX_RETRIES+1}) → {delay:.2f}s: {e}")
            time.sleep(delay); last_exc = e; continue
        except Exception as e:
            logging.error(f"[Binance] Unexpected in {name}: {type(e).__name__}: {e}")
            last_exc = e
            break
    if last_exc:
        logging.error(f"[Binance] ❌ Exhausted retries for {name}: {last_exc}")
    return None

# ← חשוב: מייצאים retry_call לשימוש חיצוני (למשל binance_trader)
def retry_call(fn, name: str):
    return _retry_call(fn, name=name)

def futures_exchange_info_safe():
    c = get_client()
    return _retry_call(lambda: c.futures_exchange_info(), name="futures_exchange_info")

# ---- Ping יציב: בדיקה ישירה ל-Spot ול-Futures, ללא תלות ב-SDK ----
def _http_ping(url: str, name: str) -> bool:
    try:
        r = _session.get(url, timeout=6)
        if r.status_code == 200:
            return True
        logging.warning(f"[Binance] {name} ping http={r.status_code} body={r.text[:120]}")
        return False
    except Exception as e:
        logging.warning(f"[Binance] {name} ping error: {e}")
        return False

def ping_and_info() -> bool:
    ok_spot = _http_ping(f"{_SPOT_HTTP}/api/v3/ping", "spot")
    ok_fapi = _http_ping(f"{_FAPI_HTTP}/fapi/v1/ping", "futures")
    ok = ok_spot or ok_fapi

    if ok:
        logging.info("[Binance] ✅ ping OK (spot=%s, futures=%s) [%s | %s]", ok_spot, ok_fapi, _SPOT_HTTP, _FAPI_HTTP)
    else:
        logging.warning("[Binance] ⚠️ ping failed (spot=%s, futures=%s) [%s | %s] – ממשיכים בכל מקרה.", ok_spot, ok_fapi, _SPOT_HTTP, _FAPI_HTTP)

    # exchange_info אופציונלי בלבד
    if _EX_INFO_ON_START:
        ei = futures_exchange_info_safe()
        if isinstance(ei, dict) and "symbols" in ei:
            logging.info("[Binance] ✅ futures_exchange_info symbols=%d", len(ei.get("symbols", [])))
        else:
            logging.warning("[Binance] ⚠️ exchange_info נכשל/לא זמין – נמשיך ללא עצירה.")

    return ok












