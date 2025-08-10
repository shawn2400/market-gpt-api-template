# utils/binance_client.py
import time, random, logging
import requests
from binance.client import Client
from binance.exceptions import BinanceAPIException, BinanceRequestException
import requests.exceptions

from utils import config

API_KEY = config.BINANCE_API_KEY
API_SECRET = config.BINANCE_API_SECRET
EXCHANGE_INFO_ON_START = config.BINANCE_EXCHANGE_INFO_ON_START
_BASE_BACKOFF = config.BINANCE_BACKOFF_BASE
_MAX_RETRIES = config.BINANCE_MAX_RETRIES

# Session עם User-Agent וטיים-אאוטים (משותף לכל הקריאות)
_session = requests.Session()
_session.headers.update({"User-Agent": "AlgoGPT/1.0 (+render) python-binance"})
_requests_params = {"timeout": 10}

def _make_client():
    if API_KEY and API_SECRET:
        logging.info("[Binance] 🔑 מפתחות נמצאו – מנסה להתחבר…")
        c = Client(API_KEY, API_SECRET, tld="com", requests_params=_requests_params, session=_session)
    else:
        logging.warning("[Binance] ללא מפתחות – מצב Public-Only (klines בלבד).")
        c = Client(None, None, tld="com", requests_params=_requests_params, session=_session)
    # בסיס Futures
    c.FUTURES_URL = "https://fapi.binance.com"
    return c

client = _make_client()

def _retry_call(fn, *, name: str):
    """
    ריטריי אקספוננציאלי עם ג׳יטר.
    מטפל ב-403/CloudFront, RateLimit (-1003/-1015), 418/429/503 ושגיאות רשת.
    מחזיר תוצאה או None אם מוצו כל הניסיונות.
    """
    last_exc = None
    for attempt in range(_MAX_RETRIES + 1):
        try:
            return fn()
        except BinanceAPIException as e:
            txt = str(e)
            if e.status_code == 403 or "CloudFront" in txt or "Invalid JSON error message" in txt:
                delay = _BASE_BACKOFF * (2 ** attempt) + random.uniform(0, 0.35)
                logging.warning(f"[Binance] 403/WAF {name} (attempt {attempt+1}/{_MAX_RETRIES+1}) → sleep {delay:.2f}s")
                time.sleep(delay); last_exc = e; continue
            if e.code in (-1003, -1015) or e.status_code in (418, 429, 503):
                delay = _BASE_BACKOFF * (2 ** attempt) + random.uniform(0, 0.35)
                logging.warning(f"[Binance] RateLimit/API {name} (attempt {attempt+1}/{_MAX_RETRIES+1}) → sleep {delay:.2f}s")
                time.sleep(delay); last_exc = e; continue
            logging.error(f"[Binance] API error in {name}: code={e.code}, http={e.status_code}, msg={e.message}")
            break
        except (BinanceRequestException, requests.exceptions.RequestException) as e:
            delay = _BASE_BACKOFF * (2 ** attempt) + random.uniform(0, 0.35)
            logging.warning(f"[Binance] Network error {name} (attempt {attempt+1}/{_MAX_RETRIES+1}) → sleep {delay:.2f}s: {e}")
            time.sleep(delay); last_exc = e; continue
        except Exception as e:
            logging.error(f"[Binance] Unexpected in {name}: {type(e).__name__}: {e}")
            last_exc = e
            break
    if last_exc:
        logging.error(f"[Binance] ❌ Exhausted retries for {name}: {last_exc}")
    return None

# עטיפות עם ריטריי לשימוש חיצוני
def ping_safe():
    return _retry_call(lambda: client.ping(), name="ping")

def futures_exchange_info_safe():
    return _retry_call(lambda: client.futures_exchange_info(), name="futures_exchange_info")

def spot_exchange_info_safe():
    return _retry_call(lambda: client.get_exchange_info(), name="spot_exchange_info")

def get_client():
    return client

def ping_and_info():
    """
    בדיקת חיבור בהפעלה.
    - לא מפילה את התהליך.
    - מחזירה False אם ping נכשל אחרי ריטריי.
    """
    try:
        ok = ping_safe()
        if ok is None:
            logging.warning("[Binance] ⚠️ ping נכשל לאחר ריטריי – נמשיך והמודולים ינסו שוב לפי צורך.")
            return False

        if EXCHANGE_INFO_ON_START:
            ei = futures_exchange_info_safe()
            if isinstance(ei, dict):
                logging.info(f"[Binance] ✅ חיבור פעיל (Futures symbols={len(ei.get('symbols', []))})")
            else:
                logging.warning("[Binance] ⚠️ דילוג futures_exchange_info בהפעלה (כשל זמני)")
        else:
            logging.info("[Binance] ✅ ping OK (דלג exchange_info בהפעלה)")
        return True
    except Exception as e:
        logging.error(f"[Binance] API error during init: {e}")
        return False

BINANCE_READY = ping_and_info()

# נקודת לוג מרכזית להגדרות (אופציונלי)
try:
    config.log_config_summary()
except Exception:
    pass







