# utils/binance_client.py

import os, time, random, logging
from dotenv import load_dotenv
import requests
from binance.client import Client
from binance.exceptions import BinanceAPIException, BinanceRequestException
import requests.exceptions

load_dotenv()

API_KEY = (os.getenv("BINANCE_API_KEY") or "").strip()
API_SECRET = (os.getenv("BINANCE_API_SECRET") or "").strip()

# אפשר לשלוט אם לבצע exchange_info בהפעלה (כבד יחסית)
EXCHANGE_INFO_ON_START = (os.getenv("BINANCE_EXCHANGE_INFO_ON_START", "false").lower() == "true")

# פרמטרים לריטריי
_BASE_BACKOFF = float(os.getenv("BINANCE_BACKOFF_BASE", "0.7"))
_MAX_RETRIES   = int(os.getenv("BINANCE_MAX_RETRIES", "5"))

# ---- יצירת Session עם User-Agent וטיים-אאוטים ----
_session = requests.Session()
_session.headers.update({"User-Agent": "AlgoGPT/1.0 (+render) python-binance"})
# python-binance ייקח מפה Timeout ברירת מחדל לקריאות
_requests_params = {"timeout": 10}

def _make_client():
    if API_KEY and API_SECRET:
        logging.info("[Binance] 🔑 מפתחות נמצאו – מנסה להתחבר...")
        c = Client(API_KEY, API_SECRET, tld="com", requests_params=_requests_params, session=_session)
    else:
        logging.warning("[Binance] ללא מפתחות – מצב Public-Only (klines בלבד).")
        c = Client(None, None, tld="com", requests_params=_requests_params, session=_session)
    # ודא בסיס פיו׳צ׳רס גלובלי
    c.FUTURES_URL = "https://fapi.binance.com"
    return c

client = _make_client()

def _retry_call(fn, *, name: str):
    """ריטריי אקספוננציאלי עם ג'יטר על קריאות בינאנס, כולל טיפול ב-403/CloudFront."""
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
            # Rate limits / זמני
            if e.code in (-1003, -1015) or e.status_code in (418, 429, 503):
                delay = _BASE_BACKOFF * (2 ** attempt) + random.uniform(0, 0.35)
                logging.warning(f"[Binance] RateLimit/API {name} (attempt {attempt+1}/{_MAX_RETRIES+1}) → sleep {delay:.2f}s")
                time.sleep(delay); last_exc = e; continue
            # אחרת – חריגה אמיתית
            logging.error(f"[Binance] API error in {name}: code={e.code}, http={e.status_code}, msg={e.message}")
            raise
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

def ping_and_info():
    """בדיקת חיבור, ללא הפלה בהפעלה: במצב כשל – מדווחים וממשיכים."""
    try:
        _retry_call(lambda: client.ping(), name="ping")
        if EXCHANGE_INFO_ON_START:
            ei = _retry_call(lambda: client.futures_exchange_info(), name="futures_exchange_info")
            if ei and isinstance(ei, dict):
                logging.info(f"[Binance] ✅ חיבור פעיל (Futures symbols={len(ei.get('symbols', []))})")
                return True
            logging.warning("[Binance] ⚠️ דילוג futures_exchange_info בהפעלה (כשל זמני או EXCHANGE_INFO_ON_START=false)")
        else:
            logging.info("[Binance] ✅ ping OK (דילוג exchange_info בהפעלה)")
        return True
    except Exception as e:
        logging.error(f"[Binance] API error: {e}")
        return False

BINANCE_READY = ping_and_info()





