# utils/binance_client.py
import os
import time
import random
import logging
import threading
from typing import Optional, Callable, List, Dict, Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util import Retry

try:
    # אופציונלי: טעינת .env אם קיים (לא חובה ב-Render)
    from dotenv import load_dotenv  # type: ignore
    load_dotenv(override=False)
except Exception:
    pass

from binance.client import Client
from binance.exceptions import BinanceAPIException, BinanceRequestException

# === טעינת קונפיג / ENV ===
def _get_bool(val: str, default: bool) -> bool:
    if val is None:
        return default
    return str(val).strip().lower() in ("1", "true", "yes", "y", "on")

try:
    from utils import config
    _API_KEY   = (getattr(config, "BINANCE_API_KEY", "") or "").strip()
    _API_SECRET= (getattr(config, "BINANCE_API_SECRET", "") or "").strip()
    _BACKOFF_BASE = float(getattr(config, "BINANCE_BACKOFF_BASE", 0.7))
    _MAX_RETRIES  = int(getattr(config, "BINANCE_MAX_RETRIES", 5))
    _EX_INFO_ON_START = bool(getattr(config, "BINANCE_EXCHANGE_INFO_ON_START", False))
    _SPOT_HTTP   = getattr(config, "BINANCE_SPOT_HTTP_BASE", "https://api.binance.com").strip()
    _FAPI_HTTP   = getattr(config, "BINANCE_FUTURES_HTTP_BASE", "https://fapi.binance.com").strip()
    _RECV_WINDOW = int(getattr(config, "BINANCE_RECV_WINDOW", 10000))
    _TIME_SYNC_INTERVAL_SEC = int(getattr(config, "BINANCE_TIME_SYNC_INTERVAL_SEC", 900))  # 15 דק'
    _ALLOWED_EGRESS_IPS = getattr(config, "BINANCE_ALLOWED_EGRESS_IPS", "").strip()
    _EGRESS_IP_ENDPOINT = getattr(config, "EGRESS_IP_ENDPOINT", "").strip()
except Exception:
    _API_KEY   = (os.getenv("BINANCE_API_KEY") or "").strip()
    _API_SECRET= (os.getenv("BINANCE_API_SECRET") or "").strip()
    _BACKOFF_BASE = float(os.getenv("BINANCE_BACKOFF_BASE", "0.7"))
    _MAX_RETRIES  = int(os.getenv("BINANCE_MAX_RETRIES", "5"))
    _EX_INFO_ON_START = _get_bool(os.getenv("BINANCE_EXCHANGE_INFO_ON_START", "false"), False)
    _SPOT_HTTP   = os.getenv("BINANCE_SPOT_HTTP_BASE", "https://api.binance.com").strip()
    _FAPI_HTTP   = os.getenv("BINANCE_FUTURES_HTTP_BASE", "https://fapi.binance.com").strip()
    _RECV_WINDOW = int(os.getenv("BINANCE_RECV_WINDOW", "10000"))
    _TIME_SYNC_INTERVAL_SEC = int(os.getenv("BINANCE_TIME_SYNC_INTERVAL_SEC", "900"))
    _ALLOWED_EGRESS_IPS = (os.getenv("BINANCE_ALLOWED_EGRESS_IPS", "") or "").strip()
    _EGRESS_IP_ENDPOINT = (os.getenv("EGRESS_IP_ENDPOINT", "") or "").strip()

# === סשן HTTP גלובלי ידידותי ל-WAF + ריטריי/Pooling ===
_session = requests.Session()
_session.trust_env = False  # לא להשתמש בפרוקסי סביבתי (מונע הפתעות ב-Render)
_session.headers.update({
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
    "Accept-Encoding": "gzip",
    "Accept-Language": "en-US,en;q=0.9",
})

_retry = Retry(
    total=_MAX_RETRIES,
    connect=_MAX_RETRIES,
    read=_MAX_RETRIES,
    status=_MAX_RETRIES,
    backoff_factor=_BACKOFF_BASE,
    status_forcelist=[403, 418, 429, 500, 502, 503, 504],
    allowed_methods=frozenset(["GET", "HEAD", "OPTIONS"]),  # לא מריצים POST בריטריי (לא אידמפוטנטי)
    raise_on_status=False,
)
_adapter = HTTPAdapter(max_retries=_retry, pool_connections=50, pool_maxsize=50)
_session.mount("https://", _adapter)
_session.mount("http://", _adapter)

_requests_params = {"timeout": 10}
_client: Optional[Client] = None
_time_sync_thread_started = False

# === Egress IP Helpers (אופציונלי) ===
def _fetch_outbound_ip(endpoints: List[str], timeout: float = 3.0) -> Optional[str]:
    for ep in endpoints:
        try:
            r = _session.get(ep, timeout=timeout)
            if r.status_code == 200:
                txt = r.text.strip()
                if txt.startswith("{"):
                    try:
                        j = r.json()
                        txt = j.get("ip") or j.get("origin") or ""
                    except Exception:
                        pass
                ip = str(txt).strip()
                if ip:
                    return ip
        except Exception:
            continue
    return None

def check_outbound_ip_against_allowlist():
    """
    אם הוגדר BINANCE_ALLOWED_EGRESS_IPS – נבדוק את ה־IP היוצא ונזהיר אם אינו ברשימה.
    """
    allowlist = [x.strip() for x in _ALLOWED_EGRESS_IPS.split(",") if x.strip()]
    if not allowlist:
        return
    endpoints = []
    if _EGRESS_IP_ENDPOINT:
        endpoints.append(_EGRESS_IP_ENDPOINT)
    endpoints += [
        "https://checkip.amazonaws.com",
        "https://api.ipify.org?format=json",
        "https://ifconfig.me/ip",
    ]
    ip = _fetch_outbound_ip(endpoints)
    if not ip:
        logging.warning("[Binance] ⚠️ לא הצלחתי לאחזר Outbound IP לצורך אימות Allowlist.")
        return
    if ip in allowlist:
        logging.info(f"[Binance] 🌐 Outbound IP OK: {ip} נמצא ב-Allowlist.")
    else:
        logging.warning(f"[Binance] 🚫 Outbound IP {ip} אינו ב-Allowlist: {allowlist}. עלול לגרום ל-403/CloudFront.")

# === יצירת לקוח Binance ===
def _make_client() -> Client:
    if _API_KEY and _API_SECRET:
        logging.info("[Binance] 🔑 נמצאו מפתחות – מנסה להתחבר…")
        c = Client(_API_KEY, _API_SECRET, tld="com", requests_params=_requests_params)
    else:
        logging.warning("[Binance] ללא מפתחות – מצב Public-Only (market data בלבד).")
        c = Client(None, None, tld="com", requests_params=_requests_params)

    # חשוב: בסיסי ה-URL חייבים לכלול את הנתיב /api ו-/fapi
    c.API_URL     = f"{_SPOT_HTTP.rstrip('/')}/api"
    c.FUTURES_URL = f"{_FAPI_HTTP.rstrip('/')}/fapi"

    # חלון קבלה (מקטין 401/Timestamp)
    try:
        c.RECV_WINDOW = _RECV_WINDOW
    except Exception:
        pass

    # שימוש בסשן הקשיח שלנו (UA + ריטריי + pooling)
    c.session = _session
    return c

def get_client() -> Client:
    """לקוח סינגלטון עם time sync ראשוני ו-thread תקופתי."""
    global _client, _time_sync_thread_started
    if _client is None:
        _client = _make_client()
        # בדיקת Outbound IP מול Allowlist (אם הוגדר)
        try:
            check_outbound_ip_against_allowlist()
        except Exception as e:
            logging.debug(f"[Binance] check_outbound_ip_against_allowlist skipped: {e}")
        # סנכרון זמן ראשוני
        try:
            sync_server_time()
        except Exception as e:
            logging.warning(f"[Binance] ⚠️ sync_server_time נכשל: {e} – נמשיך בכל מקרה.")
    if not _time_sync_thread_started and _TIME_SYNC_INTERVAL_SEC > 0:
        _time_sync_thread_started = True
        _start_periodic_time_sync(_TIME_SYNC_INTERVAL_SEC)
    return _client

# === סנכרון זמן (חד-פעמי + מחזורי) ===
def sync_server_time() -> None:
    """
    סנכרון זמן עם שרת Binance Futures ומדידת offset.
    מפחית false 401/403 מסוג Timestamp/recvWindow.
    """
    global _client
    c = _client or _make_client()

    url = f"{_FAPI_HTTP.rstrip('/')}/fapi/v1/time"
    t0 = int(time.time() * 1000)
    r = _session.get(url, timeout=6)
    r.raise_for_status()
    server_ms = int(r.json()["serverTime"])
    t1 = int(time.time() * 1000)
    rtt = (t1 - t0)
    estimated_now = t0 + rtt // 2
    offset_ms = server_ms - estimated_now
    # python-binance קורא לזה timestamp_offset
    c.timestamp_offset = offset_ms
    logging.info(f"[Binance] 🕒 time sync: offset={offset_ms}ms rtt~{rtt}ms (recvWindow={_RECV_WINDOW}ms)")

    _client = c

def _periodic_time_sync_worker(interval: int):
    while True:
        try:
            sync_server_time()
        except Exception as e:
            logging.warning(f"[Binance] time sync (periodic) נכשל: {e}")
        time.sleep(interval)

def _start_periodic_time_sync(interval: int):
    t = threading.Thread(target=_periodic_time_sync_worker, args=(interval,), daemon=True)
    t.start()
    logging.info(f"[Binance] ⏱️ periodic time sync every {interval}s הופעל")

# === Wrapper עם ריטריי/Backoff ===
def _retry_call(fn: Callable, *, name: str):
    """
    ריטריי אקספוננציאלי + jitter; טיפול ב-403/418/429/5xx/CloudFront.
    מחזיר ערך או None (לא זורק לאחר מיצוי).
    """
    last_exc = None
    for attempt in range(_MAX_RETRIES + 1):
        try:
            return fn()
        except BinanceAPIException as e:
            txt = f"http={getattr(e, 'status_code', '?')} code={getattr(e, 'code', '?')} msg={getattr(e, 'message', '')}"
            if e.status_code in (401, 403, 404, 418, 429, 500, 502, 503, 504) or "CloudFront" in str(e):
                delay = _BACKOFF_BASE * (2 ** attempt) + random.uniform(0, 0.35)
                logging.warning(f"[Binance] API {name} (attempt {attempt+1}/{_MAX_RETRIES+1}) → {delay:.2f}s ({txt})")
                if attempt == 0 and (e.status_code in (401, 403) or "Timestamp" in getattr(e, "message", "")):
                    try:
                        sync_server_time()
                    except Exception:
                        pass
                time.sleep(delay); last_exc = e; continue
            logging.error(f"[Binance] API error in {name}: {txt}")
            raise
        except (BinanceRequestException, requests.exceptions.RequestException) as e:
            # כאן תופסים גם 403/CloudFront שמגיעים מבקשות REST ישירות
            delay = _BACKOFF_BASE * (2 ** attempt) + random.uniform(0, 0.35)
            logging.warning(f"[Binance] Network/HTTP {name} (attempt {attempt+1}/{_MAX_RETRIES+1}) → {delay:.2f}s: {e}")
            time.sleep(delay); last_exc = e; continue
        except Exception as e:
            logging.error(f"[Binance] Unexpected in {name}: {type(e).__name__}: {e}")
            last_exc = e
            break
    if last_exc:
        logging.error(f"[Binance] ❌ Exhausted retries for {name}: {last_exc}")
    return None

# חשיפה חיצונית לריטריי (למודולים אחרים)
def retry_call(fn: Callable, name: str):
    return _retry_call(fn, name=name)

# === exchangeInfo – פולבק ל־HTTP אם ה-SDK לא הצליח ===
def _futures_exchange_info_http():
    url = f"{_FAPI_HTTP.rstrip('/')}/fapi/v1/exchangeInfo"
    def _do():
        r = _session.get(url, timeout=8)
        if r.status_code != 200:
            txt = (r.text or "")[:200]
            if "<HTML>" in txt.upper() or "CLOUDFRONT" in txt.upper():
                raise requests.HTTPError(f"HTTP {r.status_code} CloudFront HTML: {txt}")
            raise requests.HTTPError(f"HTTP {r.status_code}: {txt}")
        return r.json()
    return _retry_call(_do, name="futures_exchange_info(HTTP)")

def futures_exchange_info_safe() -> Dict[str, Any]:
    c = get_client()
    data = _retry_call(lambda: c.futures_exchange_info(), name="futures_exchange_info")
    if not isinstance(data, dict) or "symbols" not in data:
        data = _futures_exchange_info_http()
    return data or {}

def futures_mark_price(symbol: str):
    """
    קריאת Mark Price בפאבליק (לא חתום), עם ריטריי ידידותי ל-WAF.
    מזהה תשובת HTML של CloudFront (403) ומחלץ הודעה.
    """
    url = f"{_FAPI_HTTP.rstrip('/')}/fapi/v1/premiumIndex"
    params = {"symbol": symbol.upper()}

    def _do():
        resp = _session.get(url, params=params, timeout=6)
        if resp.status_code != 200:
            text_snip = (resp.text or "")[:200]
            if "<HTML>" in text_snip.upper() or "CLOUDFRONT" in text_snip.upper():
                raise requests.HTTPError(f"HTTP {resp.status_code} CloudFront HTML: {text_snip}")
            raise requests.HTTPError(f"HTTP {resp.status_code}: {text_snip}")
        return resp.json()

    return _retry_call(_do, name=f"premiumIndex({symbol})")

# ---- Ping ישיר ל-Spot/Futures ----
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
    spot_url = f"{_SPOT_HTTP.rstrip('/')}/api/v3/ping"
    fapi_url = f"{_FAPI_HTTP.rstrip('/')}/fapi/v1/ping"

    ok_spot = _http_ping(spot_url, "spot")
    ok_fapi = _http_ping(fapi_url, "futures")
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



















