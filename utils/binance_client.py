from __future__ import annotations

import os, hmac, time, random, threading, logging
from typing import Any, Dict, Optional, List
from hashlib import sha256
import httpx
from utils.account_router import get_account_credentials

logger = logging.getLogger("algogpt.binance.client")

HTTP_TIMEOUT_SEC = float(os.getenv("BINANCE_HTTP_TIMEOUT", "8.0"))
BINANCE_MAX_RETRIES = int(os.getenv("BINANCE_MAX_RETRIES", "5"))
BINANCE_BACKOFF_BASE = float(os.getenv("BINANCE_BACKOFF_BASE", "0.7"))

HTTP_MAX_CONNECTIONS = int(os.getenv("HTTP_MAX_CONNECTIONS", "64"))
HTTP_MAX_KEEPALIVE = int(os.getenv("HTTP_MAX_KEEPALIVE", "32"))

DEFAULT_MIN_NOTIONAL = float(os.getenv("MIN_NOTIONAL_USDT", "5"))
DEFAULT_QTY_STEP_STR = os.getenv("DEFAULT_QTY_STEP_STR", "0.001")
DEFAULT_PRICE_TICK_STR = os.getenv("DEFAULT_PRICE_TICK_STR", "0.01")

WORKING_TYPE = (os.getenv("BINANCE_WORKING_TYPE") or "MARK_PRICE").strip().upper()
PRICE_PROTECT = str(os.getenv("BINANCE_PRICE_PROTECT", "false")).lower() in ("1", "true", "yes", "on")

_clients: Dict[str, httpx.Client] = {}
_api_secrets: Dict[str, str] = {}
BASE_URL = "https://fapi.binance.com"

# ── Init client ───────────────────────────────
def get_futures_client(account_id: str = "main") -> httpx.Client:
    if account_id in _clients:
        return _clients[account_id]
    creds = get_account_credentials(account_id)
    if not creds:
        raise RuntimeError(f"❌ Account {account_id} not found in accounts_config.json")
    api_key, api_secret = creds["api_key"], creds["api_secret"]
    _api_secrets[account_id] = api_secret
    headers = {
        "X-MBX-APIKEY": api_key,
        "Accept": "application/json",
        "Accept-Encoding": "gzip",
        "User-Agent": f"AlgoGPT/{account_id} binance-client",
    }
    client = httpx.Client(
        timeout=httpx.Timeout(HTTP_TIMEOUT_SEC),
        headers=headers,
        limits=httpx.Limits(max_keepalive_connections=HTTP_MAX_KEEPALIVE, max_connections=HTTP_MAX_CONNECTIONS),
        http2=False,
    )
    _clients[account_id] = client
    return client

def _sign(account_id: str, qs: str) -> str:
    secret = _api_secrets.get(account_id)
    if not secret:
        raise RuntimeError(f"No API secret cached for account {account_id}")
    return hmac.new(secret.encode(), qs.encode(), sha256).hexdigest()

def _request(method: str, path: str, *, account_id="main", params=None, signed=False, timeout=None) -> httpx.Response:
    client = get_futures_client(account_id)
    url = f"{BASE_URL}{path}"
    attempt, last_exc = 0, None
    while attempt <= max(1, BINANCE_MAX_RETRIES):
        try:
            req_params = dict(params or {})
            if signed:
                ts = int(time.time() * 1000)
                req_params.setdefault("timestamp", ts)
                req_params.setdefault("recvWindow", 45000)
                items = [f"{k}={req_params[k]}" for k in sorted(req_params.keys())]
                req_params["signature"] = _sign(account_id, "&".join(items))
            r = client.request(method.upper(), url, params=req_params, timeout=timeout or HTTP_TIMEOUT_SEC)
            if r.status_code == 200:
                return r
            if r.status_code in (418, 429, 500, 502, 503, 504):
                time.sleep(min(10.0, BINANCE_BACKOFF_BASE * (2**attempt) + random.uniform(0, 0.4)))
            else:
                try:
                    data = r.json()
                    raise RuntimeError(f"Binance error {data.get('code')}: {data.get('msg')}")
                except Exception:
                    r.raise_for_status()
        except Exception as e:
            last_exc = e
            time.sleep(0.5 * (2**attempt))
        attempt += 1
    if last_exc: raise last_exc
    raise RuntimeError("Unspecified Binance request failure")

# ── Exchange Info helpers ─────────────────────
def futures_exchange_info_safe(account_id="main") -> Dict[str, Any]:
    try:
        r = _request("GET", "/fapi/v1/exchangeInfo", account_id=account_id)
        return r.json()
    except Exception as e:
        logger.warning(f"exchange_info error: {e}")
        return {}

def get_symbol_info(symbol: str, account_id="main") -> Dict[str, Any]:
    info = futures_exchange_info_safe(account_id)
    for s in info.get("symbols", []):
        if s.get("symbol") == symbol.upper():
            return s
    return {}

def get_symbol_filters(symbol: str, account_id="main") -> Dict[str, Any]:
    s = get_symbol_info(symbol, account_id)
    if not s: return {}
    filters = {f["filterType"]: f for f in s.get("filters", [])}
    return {
        "tickSizeStr": filters.get("PRICE_FILTER", {}).get("tickSize", DEFAULT_PRICE_TICK_STR),
        "stepSizeStr": filters.get("LOT_SIZE", {}).get("stepSize", DEFAULT_QTY_STEP_STR),
        "minNotional": float(filters.get("MIN_NOTIONAL", {}).get("notional", DEFAULT_MIN_NOTIONAL)),
    }

# ── Balances ──────────────────────────────────
def futures_balance(account_id="main") -> List[Dict[str, Any]]:
    r = _request("GET", "/fapi/v2/balance", account_id=account_id, signed=True)
    return r.json()

# ── Prices ────────────────────────────────────
def futures_mark_price(symbol: str, account_id="main") -> Optional[float]:
    """
    שליפת מחיר mark (Premium Index) מ־Binance Futures
    """
    try:
        r = _request("GET", "/fapi/v1/premiumIndex", account_id=account_id, params={"symbol": symbol.upper()})
        data = r.json()
        px = float(data.get("markPrice") or 0)
        return px if px > 0 else None
    except Exception as e:
        logger.warning(f"futures_mark_price error: {e}")
        return None

# ── Orders (שאר הפונקציות קיימות כבר) ───────
# place_limit_order(...)
# place_stop_market_order(...)
# place_take_profit_market(...)

# ── User stream keepalive ─────────────────────
# start_user_stream_keepalive(...)
# stop_user_stream(...)

__all__ = [
    "get_futures_client", "futures_balance", "futures_mark_price",
    "futures_exchange_info_safe", "get_symbol_info", "get_symbol_filters",
    "place_limit_order", "place_stop_market_order", "place_take_profit_market",
    "start_user_stream_keepalive", "stop_user_stream"
]







































































































































































