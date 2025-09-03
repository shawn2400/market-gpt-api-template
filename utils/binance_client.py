# utils/binance_client.py
from __future__ import annotations

import os
import hmac
import time
import random
import logging
from typing import Any, Dict, Optional, List
from hashlib import sha256
from decimal import Decimal, ROUND_DOWN
import httpx

from utils.account_router import get_account_credentials

logger = logging.getLogger("algogpt.binance.client")

# ──────────────────────────────────────────────
# Global config (fallbacks)
# ──────────────────────────────────────────────
HTTP_TIMEOUT_SEC = float(os.getenv("BINANCE_HTTP_TIMEOUT", "8.0"))
BINANCE_MAX_RETRIES = int(os.getenv("BINANCE_MAX_RETRIES", "5"))
BINANCE_BACKOFF_BASE = float(os.getenv("BINANCE_BACKOFF_BASE", "0.7"))

HTTP_MAX_CONNECTIONS = int(os.getenv("HTTP_MAX_CONNECTIONS", "64"))
HTTP_MAX_KEEPALIVE = int(os.getenv("HTTP_MAX_KEEPALIVE", "32"))

DEFAULT_QTY_STEP_STR = os.getenv("DEFAULT_QTY_STEP", "0.001")
DEFAULT_PRICE_TICK_STR = os.getenv("DEFAULT_PRICE_TICK", "0.1")
DEFAULT_MIN_NOTIONAL = float(os.getenv("MIN_NOTIONAL_USDT", "5"))

WORKING_TYPE = (os.getenv("BINANCE_WORKING_TYPE") or "MARK_PRICE").strip().upper()
PRICE_PROTECT = str(os.getenv("BINANCE_PRICE_PROTECT", "false")).lower() in ("1", "true", "yes", "on")

# ──────────────────────────────────────────────
# Cache לפי חשבון (account_id)
# ──────────────────────────────────────────────
_clients: Dict[str, httpx.Client] = {}
_api_secrets: Dict[str, str] = {}
BASE_URL = "https://fapi.binance.com"

def get_futures_client(account_id: str = "main") -> httpx.Client:
    if account_id in _clients:
        return _clients[account_id]

    creds = get_account_credentials(account_id)
    if not creds:
        raise RuntimeError(f"❌ Account {account_id} not found in accounts_config.json")

    api_key = creds["api_key"]
    api_secret = creds["api_secret"]
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
    logger.info(f"[BinanceClient] ✅ Futures client initialized for account_id={account_id}")
    return client

def _sign(account_id: str, qs: str) -> str:
    secret = _api_secrets.get(account_id)
    if not secret:
        raise RuntimeError(f"No API secret cached for account {account_id}")
    return hmac.new(secret.encode(), qs.encode(), sha256).hexdigest()

def _request(
    method: str,
    path: str,
    *,
    account_id: str = "main",
    params: Optional[Dict[str, Any]] = None,
    signed: bool = False,
    timeout: Optional[float] = None,
) -> httpx.Response:
    client = get_futures_client(account_id)
    url = f"{BASE_URL}{path}"
    attempt = 0
    last_exc: Optional[Exception] = None

    while attempt <= max(1, BINANCE_MAX_RETRIES):
        try:
            req_params = dict(params or {})
            if signed:
                ts = int(time.time() * 1000)
                req_params.setdefault("timestamp", ts)
                req_params.setdefault("recvWindow", 45000)
                items = [f"{k}={req_params[k]}" for k in req_params.keys()]
                req_params["signature"] = _sign(account_id, "&".join(items))

            r = client.request(method.upper(), url, params=req_params, timeout=timeout or HTTP_TIMEOUT_SEC)
            if r.status_code == 200:
                return r
            if r.status_code in (418, 429, 500, 502, 503, 504):
                delay = BINANCE_BACKOFF_BASE * (2 ** attempt)
                time.sleep(min(10.0, delay + random.uniform(0, 0.4)))
            else:
                try:
                    data = r.json()
                    raise RuntimeError(f"Binance error {data.get('code')}: {data.get('msg')}")
                except Exception:
                    r.raise_for_status()
        except Exception as e:
            last_exc = e
            time.sleep(0.5 * (2 ** attempt))
        attempt += 1

    if last_exc:
        raise last_exc
    raise RuntimeError("Unspecified Binance request failure")

# ──────────────────────────────────────────────
# Public helpers
# ──────────────────────────────────────────────
def fapi_ping(account_id: str = "main") -> bool:
    try:
        r = _request("GET", "/fapi/v1/ping", account_id=account_id)
        return r.status_code == 200
    except Exception:
        return False

def futures_mark_price(symbol: str, account_id: str = "main") -> Optional[float]:
    try:
        r = _request("GET", "/fapi/v1/premiumIndex", account_id=account_id, params={"symbol": symbol.upper()})
        px = float(r.json().get("markPrice") or 0)
        return px if px > 0 else None
    except Exception:
        return None

def futures_balance(account_id: str = "main") -> List[Dict[str, Any]]:
    r = _request("GET", "/fapi/v2/balance", account_id=account_id, signed=True)
    return r.json()

def set_leverage(symbol: str, leverage: int, account_id: str = "main") -> Dict[str, Any]:
    lev = max(1, min(int(leverage), 125))
    r = _request(
        "POST",
        "/fapi/v1/leverage",
        account_id=account_id,
        params={"symbol": symbol.upper(), "leverage": lev},
        signed=True,
    )
    return r.json()

# ──────────────────────────────────────────────
# Orders — STOP MARKET (לצרכי SL)
# ──────────────────────────────────────────────
def _round_step(value: float, step_str: str) -> str:
    step = Decimal(step_str)
    q = (Decimal(str(value)) / step).quantize(0, rounding=ROUND_DOWN) * step
    s = format(q, "f")
    return s.rstrip("0").rstrip(".") if "." in s else s

def place_stop_market(
    symbol: str,
    side: str,
    stop_price: float,
    quantity: float,
    *,
    reduce_only: bool = False,
    account_id: str = "main",
) -> Dict[str, Any]:
    """
    מציב הזמנת STOP_MARKET (ל־SL). סוגר כיוון נגדי, עם ReduceOnly לפי הצורך.
    """
    sym = symbol.upper()
    sd = side.upper()
    qty_s = _round_step(float(quantity), DEFAULT_QTY_STEP_STR)
    stop_s = _round_step(float(stop_price), DEFAULT_PRICE_TICK_STR)

    params: Dict[str, Any] = {
        "symbol": sym,
        "side": sd,
        "type": "STOP_MARKET",
        "stopPrice": stop_s,
        "quantity": qty_s,
        "workingType": WORKING_TYPE,
    }
    if reduce_only:
        params["reduceOnly"] = "true"
    if PRICE_PROTECT:
        params["priceProtect"] = "true"

    r = _request("POST", "/fapi/v1/order", account_id=account_id, params=params, signed=True)
    return r.json()




































































































































































