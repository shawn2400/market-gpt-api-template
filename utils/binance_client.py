# utils/binance_client.py
import os
import time
import random
import logging
from typing import Optional, Callable

import requests
from requests.adapters import HTTPAdapter
from urllib3.util import Retry

from dotenv import load_dotenv
load_dotenv(override=False)

from binance.client import Client
from binance.exceptions import BinanceAPIException, BinanceRequestException

# --- טעינת קונפיג / ENV ---
try:
    from utils import config
    _API_KEY = (getattr(config, "BINANCE_API_KEY", "") or "").strip()
    _API_SECRET = (getattr(config, "BINANCE_API_SECRET", "") or "").strip()
    _BACKOFF_BASE = float(getattr(config, "BINANCE_BACKOFF_BASE", 0.7))
    _MAX_RETRIES = int(getattr(config, "BINANCE_MAX_RETRIES", 5))
    _EX_INFO_ON_START = bool(getattr(config, "BINANCE_EXCHANGE_INFO_ON_START", False))
    _RECV_WINDOW = int(getattr(config, "BINANCE_RECV_WINDOW", 10000))
    _SPOT_HTTP = getattr(config, "BINANCE_SPOT_HTTP_BASE", "https://api.binance.com").strip()
    _FAPI_HTTP = getattr(config, "BINANCE_FUTURES_HTTP_BASE", "https://fapi.binance.com").strip()
except Exception:
    _API_KEY = (os.getenv("BINANCE_API_KEY") or "").strip()
    _API_SECRET = (os.getenv("BINANCE_API_SECRET") or "").strip()
    _BACKOFF_BASE = float(os.getenv("BINANCE_BACKOFF_BASE", "0.7"))
    _MAX_RETRIES = int(os.getenv("BINANCE_MAX_RETRIES", "5"))
    _EX_INFO_ON_START = (os.getenv("BINANCE_EXCHANGE_INFO_ON_START", "false").lower() == "true")
    _RECV_WINDOW = int(os.getenv("BINANCE_RECV_WINDOW", "10000"))
    _SPOT_HTTP = os.getenv("BINANCE_SPOT_HTTP_BASE", "https://api.binance.com").strip()
    _FAPI_HTTP = os.getenv("BINANCE_FUTURES_HTTP_BASE", "https://fapi.binance.com").strip()

# --- סשן HTTP גלובלי עם Retry קשוח, ידידותי ל-WAF ---
_session = requests.Session()
_session.headers.update({
    "User-Agent": "AlgoGPT/2 (Railway) python-binance",
    "Accept": "application/json",
    "Accept-Encoding": "gzip",
})
if _API_KEY:
    # לא מזיק גם לפאבליק לעתים מול WAF/פרוקסי
    _session.headers.update({"X-MBX-APIKEY": _API_KEY})

# ריטריי מאוזן: GET/HEAD/OPTIONS – 403/418/429/5xx, עם backoff ו־jitter
_retry = Retry(
    total=_MAX_RETRIES,
    connect=_MAX_RETRIES,
    read=_MAX_RETRIES,
    backoff_factor=_BACKOFF_BASE,
    status_forcelist=[403, 418, 429, 500, 502, 503, 504],
    allowed_methods=frozenset(["GET", "HEAD", "OPTIONS"]),
    raise_on_status=False,
)
_adapter = HTTPAdapter(max_retries=_retry, pool_connections=50, pool_maxsize=50)
_session.mount("https://", _adapter)
_session.mount("http://", _adapter)

_requests_params = {"timeout": 10}
_client: Optional[Client] = None
_time_synced = False

def _make_client() -> Client:
    if _API_KEY and _API_SECRET:
        logging.info("[Binance] 🔑 נמצאו מפתחות – מתחבר…")
        c = Client(_API_KEY, _API_SECRET, tld="com", requests_params=_requests_params)
    else:
        logging.warning("[Binance] ללא מפתחות – מצב Public-Only (market data בלבד).")
        c = Client(None, None, tld="com", requests_params=_requests_params)

    # בסיסים עדכניים
    c.API_URL = _SPOT_HTTP
    c.FUTURES_URL = _FAPI_HTTP
    c.session = _session
    # timestamp_offset ייקבע אחרי סנכרון זמן
    return c

def get_client() -> Client:
    global _client, _time_synced
    if _client is None:
        _client = _make_client()
        # נסנכרן זמן מיד בהפעלה כדי למנוע 403/recvWindow
        try:
            sync_server_time()
            _time_synced = True
        except Exception as e:
            logging.warning(f"[Binance] ⚠️ sync_server_time נכשל: {e} – נמשיך בכל מקרה.")
    return _client

def sync_server_time() -> None:
    """
    סנכרון זמן: מחשב drift ומגדיר timestamp_offset ב־python-binance.
    מפחית false 403/401 ('Timestamp for this request was 1000ms ahead/behind').
    """
    c = _client or _make_client()
    # Futures עדיף (אותו NTP, פחות גשרים)
    url = f"{_FAPI_HTTP}/fapi/v1/time"
    t0 = int(time.time() * 1000)
    r = _session.get(url, timeout=5)
    r.raise_for_status()
    server_ms = int(r.json()["serverTime"])
    t1 = int(time.time() * 1000)
    # הערכת latency ממוצעת
    rtt = (t1 - t0)
    estimated_now = t0 + rtt // 2
    offset_ms = server_ms - estimated_now
    c.timestamp_offset = offset_ms  # שדה קיים ב־python-binance
    # שמירה בלקוח הגלובלי
    global _client
    _client = c
    logging.info(f"[Binance] 🕒 time sync: offset={offset_ms}ms rtt~{rtt}ms (recvWindow={_RECV_WINDOW}ms)")

def _retry_call(fn: Callable, *, name: str):
    """
    קריאה עם ריטריי אקספוננציאלי + jitter; טיפול ב-403/429/CloudFront.
    מחזיר ערך או None (לא זורק אחרי מיצוי).
    """
    last_exc = None
    for attempt in range(_MAX_RETRIES + 1):
        try:
            return fn()
        except BinanceAPIException as e:
            txt = f"http={getattr(e, 'status_code', '?')} code={getattr(e, 'code', '?')} msg={getattr(e, 'message', '')}"
            if e.status_code in (401, 403, 418, 429, 500, 502, 503, 504) or "CloudFront" in str(e):
                delay = _BACKOFF_BASE * (2 ** attempt) + random.uniform(0, 0.35)
                logging.warning(f"[Binance] API {name} (attempt {attempt+1}/{_MAX_RETRIES+1}) → {delay:.2f}s ({txt})")
                time.sleep(delay); last_exc = e
                # אם נראה שסנכרון זמן בעייתי – ננסה פעם אחת לרענן
                if attempt == 0 and ("Timestamp" in e.message or e.status_code in (401, 403)):
                    try:
                        sync_server_time()
                    except Exception:
                        pass
                continue
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

# ← מייצאים לשימוש חיצוני
def retry_call(fn: Callable, name: str):
    return _retry_call(fn, name=name)

# --- Public helpers עם recvWindow/offset מיושמים ב־Client ---
def futures_exchange_info_safe():
    c = get_client()
    return _retry_call(lambda: c.futures_exchange_info(), name="futures_exchange_info")

def futures_mark_price(symbol: str):
    """
    קריאת Mark Price בפאבליק (לא חתום), עם ריטריי.
    """
    url = f"{_FAPI_HTTP}/fapi/v1/premiumIndex"
    params = {"symbol": symbol.upper()}
    def _do():
        resp = _session.get(url, params=params, timeout=5)
        if resp.status_code != 200:
            raise BinanceRequestException(resp, "HTTP %s" % resp.status_code)
        return resp.json()
    return _retry_call(_do, name=f"premiumIndex({symbol})")

# ---- Ping יציב: בדיקה ישירה ל-Spot ול-Futures ----
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

    if _EX_INFO_ON_START:
        ei = futures_exchange_info_safe()
        if isinstance(ei, dict) and "symbols" in ei:
            logging.info("[Binance] ✅ futures_exchange_info symbols=%d", len(ei.get("symbols", [])))
        else:
            logging.warning("[Binance] ⚠️ exchange_info נכשל/לא זמין – נמשיך ללא עצירה.")

    return ok











