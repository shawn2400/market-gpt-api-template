# utils/binance_spot_client.py
from __future__ import annotations

import os
import hmac
import time
import random
import threading
import logging
from typing import Any, Dict, Optional, List
from hashlib import sha256
import httpx

from utils.account_router import get_account_credentials

logger = logging.getLogger("algogpt.binance.spot_client")

# ──────────────────────────────────────────────
# Global config
# ──────────────────────────────────────────────
HTTP_TIMEOUT_SEC = float(os.getenv("BINANCE_HTTP_TIMEOUT", "8.0"))
BINANCE_MAX_RETRIES = int(os.getenv("BINANCE_MAX_RETRIES", "5"))
BINANCE_BACKOFF_BASE = float(os.getenv("BINANCE_BACKOFF_BASE", "0.7"))

HTTP_MAX_CONNECTIONS = int(os.getenv("HTTP_MAX_CONNECTIONS", "64"))
HTTP_MAX_KEEPALIVE = int(os.getenv("HTTP_MAX_KEEPALIVE", "32"))

BASE_URL = (os.getenv("BINANCE_SPOT_HTTP_BASE") or "https://api.binance.com").rstrip("/")

# ──────────────────────────────────────────────
# Cache לפי חשבון
# ──────────────────────────────────────────────
_clients: Dict[str, httpx.Client] = {}
_api_secrets: Dict[str, str] = {}

def get_spot_client(account_id: str = "spot1") -> httpx.Client:
    """
    מחזיר httpx.Client עבור חשבון SPOT נתון.
    נבנה פעם אחת בלבד ושמור ב־cache.
    """
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
        "User-Agent": f"AlgoGPT/{account_id} binance-spot-client",
    }
    client = httpx.Client(
        timeout=httpx.Timeout(HTTP_TIMEOUT_SEC),
        headers=headers,
        limits=httpx.Limits(max_keepalive_connections=HTTP_MAX_KEEPALIVE,
                            max_connections=HTTP_MAX_CONNECTIONS),
        http2=False,
    )
    _clients[account_id] = client
    logger.info(f"[BinanceSpotClient] ✅ Spot client initialized for account_id={account_id}")
    return client

# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────
def _sign(account_id: str, qs: str) -> str:
    secret = _api_secrets.get(account_id)
    if not secret:
        raise RuntimeError(f"No API secret cached for account {account_id}")
    return hmac.new(secret.encode(), qs.encode(), sha256).hexdigest()

def _request(
    method: str,
    path: str,
    *,
    account_id: str = "spot1",
    params: Optional[Dict[str, Any]] = None,
    signed: bool = False,
    timeout: Optional[float] = None,
) -> httpx.Response:
    client = get_spot_client(account_id)
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
                    raise RuntimeError(f"Binance Spot error {data.get('code')}: {data.get('msg')}")
                except Exception:
                    r.raise_for_status()
        except Exception as e:
            last_exc = e
            time.sleep(0.5 * (2 ** attempt))
        attempt += 1

    if last_exc:
        raise last_exc
    raise RuntimeError("Unspecified Binance SPOT request failure")

# ──────────────────────────────────────────────
# Spot API Examples
# ──────────────────────────────────────────────
def spot_ping(account_id: str = "spot1") -> bool:
    try:
        r = _request("GET", "/api/v3/ping", account_id=account_id)
        return r.status_code == 200
    except Exception:
        return False

def spot_price(symbol: str, account_id: str = "spot1") -> Optional[float]:
    try:
        r = _request("GET", "/api/v3/ticker/price", account_id=account_id, params={"symbol": symbol.upper()})
        px = float(r.json().get("price") or 0)
        return px if px > 0 else None
    except Exception:
        return None

def spot_balance(account_id: str = "spot1") -> List[Dict[str, Any]]:
    r = _request("GET", "/api/v3/account", account_id=account_id, signed=True)
    return r.json().get("balances", [])


