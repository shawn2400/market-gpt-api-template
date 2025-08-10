# utils/binance_client.py
import os
import time
import random
import logging
import requests
from typing import Optional, Callable, Any

from dotenv import load_dotenv
load_dotenv(override=False)

from binance.client import Client
from binance.exceptions import BinanceAPIException, BinanceRequestException

# === קונפיג/ENV ===
try:
    from utils import config
    _API_KEY = (config.BINANCE_API_KEY or "").strip()
    _API_SECRET = (config.BINANCE_API_SECRET or "").strip()
    _BACKOFF_BASE = float(getattr(config, "BINANCE_BACKOFF_BASE", 0.7))
    _MAX_RETRIES = int(getattr(config, "BINANCE_MAX_RETRIES", 5))
    _EX_INFO_ON_START = bool(getattr(config, "BINANCE_EXCHANGE_INFO_ON_START", False))
    _FAPI_BASE = getattr(config, "BINANCE_FUTURES_HTTP_BASE", "https://fapi.binance.com")
    _SPOT_BASE = getattr(config, "BINANCE_SPOT_HTTP_BASE", "https://api.binance.com")
except Exception:
    _API_KEY = (os.getenv("BINANCE_API_KEY") or "").strip()
    _API_SECRET = (os.getenv("BINANCE_API_SECRET") or "").strip()
    _BACKOFF_BASE = float(os.getenv("BINANCE_BACKOFF_BASE", "0.7"))
    _MAX_RETRIES = int(os.getenv("BINANCE_MAX_RETRIES", "5"))
    _EX_INFO_ON_START = os.getenv("BINANCE_EXCHANGE_INFO_ON_START", "false").lower() in ("1", "true", "yes", "on")
    _FAPI_BASE = os.getenv("BINANCE_FUTURES_HTTP_BASE", "https://fapi.binance.com")
    _SPOT_BASE = os.getenv("BINANCE_SPOT_HTTP_BASE", "https://api.binance.com")

# === סשן HTTP גלובלי ידידותי ל-WAF/פרוקסי ===
_session = requests.Session()
_session.trust_env = True  # כדי ש-HTTP(S)_PROXY מהסביבה יעבדו
_session.headers.update({
    "User-Agent": "AlgoGPT/2 (Render) python-binance",
    "Accept": "application/json",
    "Accept-Encoding": "gzip",
})
if _API_KEY:
    # גם לקריאות public זה לא מזיק, לפעמים עוזר מול CloudFront/WAF
    _session.headers.update({"X-MBX-APIKEY": _API_KEY})

_requests_params = {"timeout": 10}

_client: Optional[Client] = None  # ייווצר Lazy

def _make_client() -> Client:
    """
    יוצר לקוח python-binance. לא מעביר 'session' לבנאי (לא נתמך בגרסה זו),
    אלא מזריק את ה-Session לאחר מכן. מגדיר בסיסי HTTP נכונים.
    """
    if _API_KEY and _API_SECRET:
        logging.info("[Binance] 🔑 נמצאו מפתחות – מנסה להתחבר…")
        c = Client(_API_KEY, _API_SECRET, tld="com", requests_params=_requests_params)
    else:
        logging.warning("[Binance] ללא מפתחות – מצב Public-Only (קריאות ציבוריות).")
        c = Client(None, None, tld="com", requests_params=_requests_params)

    # בסיסי API מותאמים
    try:
        c.API_URL = _SPOT_BASE
    except Exception:
        pass
    try:
        c.FUTURES_URL = _FAPI_BASE
    except Exception:
        c.FUTURES_URL = "https://fapi.binance.com"

    # הזרקת session מותאם (Headers/Proxy/Keep-Alive)
    c.session = _session
    return c

def get_client() -> Client:
    """
    מחזיר לקוח סינגלטון. יצירה Lazy (ללא קריאות רשת בזמן הייבוא).
    """
    global _client
    if _client is None:
        _client = _make_client()
    return _client

# תאימות לאחור: חלק מהקוד הישן עשה `from utils.binance_client import client`
# נותן אובייקט "עצל" שמעביר כול קריאה ל-get_client().
class _LazyClient:
    def __getattr__(self, item):
        return getattr(get_client(), item)

client = _LazyClient()  # לשמירת תאימות

def _retry_call(fn: Callable[[], Any], *, name: str):
    """
    קריאה עם ריטריי אקספוננציאלי + ג'יטר.
    מטפל ב-403/CloudFront/WAF, RateLimit (-1003/-1015) ושגיאות רשת.
    """
    last_exc = None
    for attempt in range(_MAX_RETRIES + 1):
        try:
            return fn()
        except BinanceAPIException as e:
            txt = f"http={getattr(e, 'status_code', '?')} code={getattr(e, 'code', '?')} msg={getattr(e, 'message', '')}"
            s = int(getattr(e, "status_code", 0) or 0)
            c = int(getattr(e, "code", 0) or 0)
            # WAF/CloudFront/429/503
            if s in (403, 418, 429, 503) or c in (-1003, -1015) or "CloudFront" in str(e) or "Invalid JSON error message" in str(e):
                delay = _BACKOFF_BASE * (2 ** attempt) + random.uniform(0, 0.35)
                logging.warning(f"[Binance] ⏳ {name} (attempt {attempt+1}/{_MAX_RETRIES+1}) → {delay:.2f}s | {txt}")
                time.sleep(delay); last_exc = e; continue
            logging.error(f"[Binance] API error in {name}: {txt}")
            raise
        except (BinanceRequestException, requests.exceptions.RequestException) as e:
            delay = _BACKOFF_BASE * (2 ** attempt) + random.uniform(0, 0.35)
            logging.warning(f"[Binance] 🌐 Network {name} (attempt {attempt+1}/{_MAX_RETRIES+1}) → {delay:.2f}s: {e}")
            time.sleep(delay); last_exc = e; continue
        except Exception as e:
            logging.error(f"[Binance] ❌ Unexpected in {name}: {type(e).__name__}: {e}")
            last_exc = e
            break
    if last_exc:
        logging.error(f"[Binance] ❌ Exhausted retries for {name}: {last_exc}")
    return None

# יצוא שם ציבורי לתאימות (קוד אחר משתמש בו)
retry_call = _retry_call

def futures_exchange_info_safe():
    """
    שליפת exchangeInfo ל-Futures עם ריטריי. מחזיר dict או None.
    """
    c = get_client()
    return _retry_call(lambda: c.futures_exchange_info(), name="futures_exchange_info")

def ping_and_info() -> bool:
    """
    פינג קצר ל-Binance; אופציונלית טוען exchange_info בתחילת שרת.
    מחזיר True אם תקין, False אם לא.
    """
    try:
        c = get_client()
        _retry_call(lambda: c.ping(), name="ping")
        if _EX_INFO_ON_START:
            ei = futures_exchange_info_safe()
            if isinstance(ei, dict):
                logging.info("[Binance] ✅ חיבור פעיל (Futures symbols=%d)", len(ei.get("symbols", [])))
                return True
            logging.warning("[Binance] ⚠️ exchange_info נכשל/אופציונלי – ממשיכים.")
        else:
            logging.info("[Binance] ✅ ping OK (דילוג exchange_info לפי קונפיג).")
        return True
    except Exception as e:
        logging.error(f"[Binance] API error on startup: {e}")
        return False

__all__ = [
    "get_client", "client",
    "_retry_call", "retry_call",
    "futures_exchange_info_safe", "ping_and_info",
]









