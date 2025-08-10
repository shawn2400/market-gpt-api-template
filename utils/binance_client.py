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

try:
    # הגדרות אחידות מהקונפיג (אם קיים)
    from utils import config
    _API_KEY = (config.BINANCE_API_KEY or "").strip()
    _API_SECRET = (config.BINANCE_API_SECRET or "").strip()
    _BACKOFF_BASE = float(getattr(config, "BINANCE_BACKOFF_BASE", 0.7))
    _MAX_RETRIES = int(getattr(config, "BINANCE_MAX_RETRIES", 5))
    _EX_INFO_ON_START = bool(getattr(config, "BINANCE_EXCHANGE_INFO_ON_START", False))
except Exception:
    # פולבק ישיר מה-ENV
    _API_KEY = (os.getenv("BINANCE_API_KEY") or "").strip()
    _API_SECRET = (os.getenv("BINANCE_API_SECRET") or "").strip()
    _BACKOFF_BASE = float(os.getenv("BINANCE_BACKOFF_BASE", "0.7"))
    _MAX_RETRIES = int(os.getenv("BINANCE_MAX_RETRIES", "5"))
    _EX_INFO_ON_START = (os.getenv("BINANCE_EXCHANGE_INFO_ON_START", "false").lower() == "true")

# --- סשן HTTP גלובלי עם כותרות ידידותיות ל-WAF ---
_session = requests.Session()
_session.headers.update({
    "User-Agent": "AlgoGPT/1.0 (Render) python-binance",
    "Accept": "application/json",
    "Accept-Encoding": "gzip",
})
if _API_KEY:
    # לא מזיק גם לקריאות public, לפעמים עוזר מול CloudFront/WAF
    _session.headers.update({"X-MBX-APIKEY": _API_KEY})

_requests_params = {"timeout": 10}

_client: Optional[Client] = None

def _make_client() -> Client:
    if _API_KEY and _API_SECRET:
        logging.info("[Binance] 🔑 מפתחות נמצאו – מנסה להתחבר…")
        c = Client(_API_KEY, _API_SECRET, tld="com", requests_params=_requests_params)
    else:
        logging.warning("[Binance] ללא מפתחות – מצב Public-Only (klines בלבד).")
        c = Client(None, None, tld="com", requests_params=_requests_params)

    # בסיס Futures תקין
    c.FUTURES_URL = "https://fapi.binance.com"
    # הזרקת הסשן המותאם (headers וכו’)
    c.session = _session
    return c

def get_client() -> Client:
    global _client
    if _client is None:
        _client = _make_client()
    return _client

def _retry_call(fn, *, name: str):
    """קריאה עם ריטריי אקספוננציאלי + ג’יטר; טיפול ב-403/CloudFront/RateLimit."""
    last_exc = None
    for attempt in range(_MAX_RETRIES + 1):
        try:
            return fn()
        except BinanceAPIException as e:
            txt = f"http={getattr(e, 'status_code', '?')} code={getattr(e, 'code', '?')} msg={getattr(e, 'message', '')}"
            if e.status_code == 403 or "CloudFront" in str(e) or "Invalid JSON error message" in str(e):
                delay = _BACKOFF_BASE * (2 ** attempt) + random.uniform(0, 0.35)
                logging.warning(f"[Binance] 403/WAF {name} (attempt {attempt+1}/{_MAX_RETRIES+1}) → {delay:.2f}s ({txt})")
                time.sleep(delay); last_exc = e; continue
            if e.code in (-1003, -1015) or e.status_code in (418, 429, 503):
                delay = _BACKOFF_BASE * (2 ** attempt) + random.uniform(0, 0.35)
                logging.warning(f"[Binance] RateLimit/API {name} (attempt {attempt+1}/{_MAX_RETRIES+1}) → {delay:.2f}s ({txt})")
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

def futures_exchange_info_safe():
    c = get_client()
    return _retry_call(lambda: c.futures_exchange_info(), name="futures_exchange_info")

def ping_and_info() -> bool:
    try:
        c = get_client()
        _retry_call(lambda: c.ping(), name="ping")
        if _EX_INFO_ON_START:
            ei = futures_exchange_info_safe()
            if isinstance(ei, dict):
                logging.info("[Binance] ✅ חיבור פעיל (Futures symbols=%d)", len(ei.get("symbols", [])))
                return True
            logging.warning("[Binance] ⚠️ exchange_info נכשל/אופציונלי – נמשיך.")
        else:
            logging.info("[Binance] ✅ ping OK (דילוג exchange_info לפי קונפיג).")
        return True
    except Exception as e:
        logging.error(f"[Binance] API error on startup: {e}")
        return False









