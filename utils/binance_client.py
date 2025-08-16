# utils/binance_client.py
import os
import time
import hmac
import json
import random
import logging
import hashlib
import threading
from typing import Optional, Callable, List, Dict, Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util import Retry

try:
    from dotenv import load_dotenv  # type: ignore
    load_dotenv(override=False)
except Exception:
    pass

from binance.client import Client
from binance.exceptions import BinanceAPIException, BinanceRequestException

# -------------------- utils --------------------
def _clean(s: Optional[str]) -> str:
    return (s or "").replace("\r", "").replace("\n", "").strip().strip("\"'").strip()

def _get_bool(val: Optional[str], default: bool) -> bool:
    if val is None:
        return default
    return str(val).strip().lower() in ("1", "true", "yes", "y", "on")

def _len_or_zero(s: Optional[str]) -> int:
    return len(s) if s else 0

# -------------------- config --------------------
try:
    from utils import config
    _API_KEY_RAW    = getattr(config, "BINANCE_API_KEY", "")
    _API_SECRET_RAW = getattr(config, "BINANCE_API_SECRET", "")
    _BACKOFF_BASE   = float(getattr(config, "BINANCE_BACKOFF_BASE", 0.7))
    _MAX_RETRIES    = int(getattr(config, "BINANCE_MAX_RETRIES", 5))
    _EX_INFO_ON_START = bool(getattr(config, "BINANCE_EXCHANGE_INFO_ON_START", False))
    _SPOT_HTTP      = getattr(config, "BINANCE_SPOT_HTTP_BASE", "https://api.binance.com").strip()
    _FAPI_HTTP      = getattr(config, "BINANCE_FUTURES_HTTP_BASE", "https://fapi.binance.com").strip()
    _RECV_WINDOW    = int(getattr(config, "BINANCE_RECV_WINDOW", 10000))
    _TIME_SYNC_INTERVAL_SEC = int(getattr(config, "BINANCE_TIME_SYNC_INTERVAL_SEC", 900))
    _ALLOWED_EGRESS_IPS = getattr(config, "BINANCE_ALLOWED_EGRESS_IPS", "").strip()
    _EGRESS_IP_ENDPOINT  = getattr(config, "EGRESS_IP_ENDPOINT", "").strip()
    _TIME_SYNC_MAX_RTT_MS = int(getattr(config, "TIME_SYNC_MAX_RTT_MS", 800))
    _TIME_SYNC_MAX_ABS_OFFSET_MS = int(getattr(config, "TIME_SYNC_MAX_ABS_OFFSET_MS", 1500))
except Exception:
    _API_KEY_RAW    = os.getenv("BINANCE_API_KEY", "")
    _API_SECRET_RAW = os.getenv("BINANCE_API_SECRET", "")
    _BACKOFF_BASE   = float(os.getenv("BINANCE_BACKOFF_BASE", "0.7"))
    _MAX_RETRIES    = int(os.getenv("BINANCE_MAX_RETRIES", "5"))
    _EX_INFO_ON_START = _get_bool(os.getenv("BINANCE_EXCHANGE_INFO_ON_START"), False)
    _SPOT_HTTP      = os.getenv("BINANCE_SPOT_HTTP_BASE", "https://api.binance.com").strip()
    _FAPI_HTTP      = os.getenv("BINANCE_FUTURES_HTTP_BASE", "https://fapi.binance.com").strip()
    _RECV_WINDOW    = int(os.getenv("BINANCE_RECV_WINDOW", "10000"))
    _TIME_SYNC_INTERVAL_SEC = int(os.getenv("BINANCE_TIME_SYNC_INTERVAL_SEC", "900"))
    _ALLOWED_EGRESS_IPS = (os.getenv("BINANCE_ALLOWED_EGRESS_IPS", "") or "").strip()
    _EGRESS_IP_ENDPOINT  = (os.getenv("EGRESS_IP_ENDPOINT", "") or "").strip()
    _TIME_SYNC_MAX_RTT_MS = int(os.getenv("TIME_SYNC_MAX_RTT_MS", "800"))
    _TIME_SYNC_MAX_ABS_OFFSET_MS = int(os.getenv("TIME_SYNC_MAX_ABS_OFFSET_MS", "1500"))

_API_KEY    = _clean(_API_KEY_RAW)
_API_SECRET = _clean(_API_SECRET_RAW)

def get_keys_cleaned() -> Dict[str, Any]:
    """מחזיר מפתחות אחרי ניקוי + מידע דיאגנוסטי בסיסי."""
    return {
        "api_key": _API_KEY,
        "api_secret": _API_SECRET,
        "key_len": _len_or_zero(_API_KEY),
        "secret_len": _len_or_zero(_API_SECRET),
    }

def assert_keys_ok() -> None:
    if _len_or_zero(_API_KEY) < 32 or _len_or_zero(_API_SECRET) < 32:
        raise RuntimeError(f"BINANCE keys look invalid (len={_len_or_zero(_API_KEY)}/{_len_or_zero(_API_SECRET)}). "
                           "Paste without quotes/newlines and ensure Futures-enabled & IP allowlist if used.")

# -------------------- session --------------------
_session = requests.Session()
_session.trust_env = False
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
    allowed_methods=frozenset(["GET", "HEAD", "OPTIONS"]),
    raise_on_status=False,
)
_adapter = HTTPAdapter(max_retries=_retry, pool_connections=50, pool_maxsize=50)
_session.mount("https://", _adapter)
_session.mount("http://", _adapter)

_requests_params = {"timeout": 10}
_client: Optional[Client] = None
_time_sync_thread_started = False

# -------------------- egress/allowlist --------------------
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

def check_outbound_ip_against_allowlist() -> None:
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

# -------------------- client & time sync --------------------
def _make_client() -> Client:
    if _API_KEY and _API_SECRET:
        logging.info("[Binance] 🔑 נמצאו מפתחות – מנסה להתחבר…")
        c = Client(_API_KEY, _API_SECRET, tld="com", requests_params=_requests_params)
    else:
        logging.warning("[Binance] ללא מפתחות – מצב Public-Only (market data בלבד).")
        c = Client(None, None, tld="com", requests_params=_requests_params)

    c.API_URL     = f"{_SPOT_HTTP.rstrip('/')}/api"
    c.FUTURES_URL = f"{_FAPI_HTTP.rstrip('/')}/fapi"

    try:
        c.RECV_WINDOW = _RECV_WINDOW
    except Exception:
        pass

    c.session = _session
    return c

def get_client() -> Client:
    global _client, _time_sync_thread_started
    if _client is None:
        _client = _make_client()
        try:
            check_outbound_ip_against_allowlist()
        except Exception as e:
            logging.debug(f"[Binance] check_outbound_ip_against_allowlist skipped: {e}")
        try:
            sync_server_time()
        except Exception as e:
            logging.warning(f"[Binance] ⚠️ sync_server_time נכשל: {e} – נמשיך בכל מקרה.")
    if not _time_sync_thread_started and _TIME_SYNC_INTERVAL_SEC > 0:
        _time_sync_thread_started = True
        _start_periodic_time_sync(_TIME_SYNC_INTERVAL_SEC)
    return _client

def sync_server_time() -> Dict[str, Any]:
    global _client
    c = _client or _make_client()

    url = f"{_FAPI_HTTP.rstrip('/')}/fapi/v1/time"
    t0 = time.time()
    try:
        r = _session.get(url, timeout=3)
        t1 = time.time()
        r.raise_for_status()
        srv_ms = int(r.json()["serverTime"])
        rtt_ms = int((t1 - t0) * 1000)
        mid_ms = int(((t0 + t1) / 2) * 1000)
        offset_ms = srv_ms - mid_ms

        accept = (rtt_ms <= _TIME_SYNC_MAX_RTT_MS) and (abs(offset_ms) <= _TIME_SYNC_MAX_ABS_OFFSET_MS)
        if not accept:
            logging.warning(f"[Binance] time sync ignored: offset={offset_ms}ms rtt~{rtt_ms}ms "
                            f"(thr={_TIME_SYNC_MAX_ABS_OFFSET_MS}/{_TIME_SYNC_MAX_RTT_MS})")
            return {"ok": False, "offset_ms": offset_ms, "rtt_ms": rtt_ms, "applied": False}

        c.timestamp_offset = offset_ms
        logging.info(f"[Binance] 🕒 time sync: offset={offset_ms}ms rtt~{rtt_ms}ms (recvWindow={_RECV_WINDOW}ms)")
        _client = c
        return {"ok": True, "offset_ms": offset_ms, "rtt_ms": rtt_ms, "applied": True}
    except Exception as e:
        logging.warning(f"[Binance] time sync failed: {e}")
        return {"ok": False, "error": str(e), "applied": False}

def _periodic_time_sync_worker(interval: int) -> None:
    while True:
        try:
            sync_server_time()
        except Exception as e:
            logging.warning(f"[Binance] time sync (periodic) נכשל: {e}")
        time.sleep(interval)

def _start_periodic_time_sync(interval: int) -> None:
    t = threading.Thread(target=_periodic_time_sync_worker, args=(interval,), daemon=True)
    t.start()
    logging.info(f"[Binance] ⏱️ periodic time sync every {interval}s הופעל")

# -------------------- retry wrapper --------------------
def _retry_call(fn: Callable, *, name: str):
    last_exc = None
    for attempt in range(_MAX_RETRIES + 1):
        try:
            return fn()
        except BinanceAPIException as e:
            status = getattr(e, 'status_code', '?')
            code   = getattr(e, 'code', '?')
            msg    = getattr(e, 'message', '') or ''
            txt = f"http={status} code={code} msg={msg}"

            if str(code) in ("-2014", "-2015"):
                logging.error("[Binance] ❌ Auth error %s: %s. בדוק KEY/SECRET, IP Allowlist, ושה-Futures מאופשר.", code, msg)

            if status in (401, 403, 404, 418, 429, 500, 502, 503, 504) or "CloudFront" in str(e):
                delay = _BACKOFF_BASE * (2 ** attempt) + random.uniform(0, 0.35)
                logging.warning(f"[Binance] API {name} (attempt {attempt+1}/{_MAX_RETRIES+1}) → {delay:.2f}s ({txt})")
                if attempt == 0 and (status in (401, 403) or "Timestamp" in msg):
                    try:
                        sync_server_time()
                    except Exception:
                        pass
                time.sleep(delay); last_exc = e; continue

            logging.error(f"[Binance] API error in {name}: {txt}")
            raise
        except (BinanceRequestException, requests.exceptions.RequestException) as e:
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

def retry_call(fn: Callable, name: str):
    return _retry_call(fn, name=name)

# -------------------- HTTP helpers --------------------
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

def get_price(symbol: str) -> Optional[float]:
    try:
        data = futures_mark_price(symbol.upper())
        if isinstance(data, dict):
            mp = data.get("markPrice")
            if mp is not None:
                return float(mp)
    except Exception as e:
        logging.warning(f"[Binance] get_price failed for {symbol}: {e}")
    return None

# -------------------- Signed auth probe --------------------
def _hmac_sha256(secret: str, msg: str) -> str:
    return hmac.new(secret.encode(), msg.encode(), hashlib.sha256).hexdigest()

def auth_probe_signed() -> None:
    """
    מבצע קריאה חתומה פשוטה אל /fapi/v2/balance כדי לאמת KEY/SECRET/IP/הרשאות.
    זורק RuntimeError עם הודעה ברורה במקרה כשל.
    """
    assert_keys_ok()
    ts = int(time.time() * 1000)
    query = f"timestamp={ts}&recvWindow={_RECV_WINDOW}"
    sig = _hmac_sha256(_API_SECRET, query)
    url = f"{_FAPI_HTTP.rstrip('/')}/fapi/v2/balance?{query}&signature={sig}"
    headers = {"X-MBX-APIKEY": _API_KEY, "Accept": "application/json"}
    r = _session.get(url, headers=headers, timeout=6)
    ct = (r.headers.get("Content-Type") or "").lower()
    body = {}
    try:
        body = r.json() if "json" in ct else {}
    except Exception:
        body = {}

    if r.status_code == 200:
        return
    code = body.get("code")
    msg  = body.get("msg") or body.get("message") or r.text
    if code in (-2014, -2015) or r.status_code in (401, 403):
        raise RuntimeError(f"Binance auth failed ({code}): {msg}. "
                           "Check: trimmed KEY/SECRET (no quotes/newlines), Futures enabled on the key, and IP allowlist.")
    raise RuntimeError(f"Binance signed probe failed http={r.status_code}: {msg}")

# -------------------- Convenience proxy --------------------
class _LazyClientProxy:
    def __getattr__(self, name: str):
        return getattr(get_client(), name)
    def __repr__(self):
        return "<LazyBinanceClientProxy>"

client = _LazyClientProxy()























