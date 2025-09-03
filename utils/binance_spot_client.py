# ✅ גרסה מוכנה לעבודה: utils/binance_spot_client.py

from __future__ import annotations
import os, hmac, time, random, threading, logging
from typing import Any, Dict, Optional, List
from hashlib import sha256
from decimal import Decimal

import httpx

logger = logging.getLogger("algogpt.binance.spot")

# ──────────────────────────────────────────────────────────────────────────────
# ENV / Spot base
# ──────────────────────────────────────────────────────────────────────────────

def _clean_env(s: Optional[str]) -> str:
    return (s or "").strip().strip('"').replace("\r", "").replace("\n", "").replace("\t", "")

API_KEY    = _clean_env(os.getenv("BINANCE_API_KEY"))
API_SECRET = _clean_env(os.getenv("BINANCE_API_SECRET"))
BASE       = (os.getenv("BINANCE_SPOT_HTTP_BASE") or "https://api.binance.com").rstrip("/")

RECV_WINDOW = int(os.getenv("BINANCE_RECV_WINDOW", "45000"))
HTTP_TIMEOUT_SEC = float(os.getenv("BINANCE_HTTP_TIMEOUT", "8.0"))

HEADERS = {
    "X-MBX-APIKEY": API_KEY,
    "Accept": "application/json",
    "User-Agent": "AlgoGPT/2 spot-client",
}

CLIENT = httpx.Client(timeout=httpx.Timeout(HTTP_TIMEOUT_SEC), headers=HEADERS)

def _ts_ms() -> int:
    return int(time.time() * 1000)

def _sign(qs: str) -> str:
    return hmac.new(API_SECRET.encode(), qs.encode(), sha256).hexdigest()

def _request(method: str, path: str, *, params: Optional[Dict[str, Any]] = None, signed: bool = False) -> httpx.Response:
    url = f"{BASE}{path}"
    req_params = dict(params or {})
    if signed:
        req_params["timestamp"] = _ts_ms()
        req_params["recvWindow"] = RECV_WINDOW
        items = [f"{k}={req_params[k]}" for k in req_params.keys()]
        req_params["signature"] = _sign("&".join(items))
    return CLIENT.request(method.upper(), url, params=req_params)

# ──────────────────────────────────────────────────────────────────────────────
# Spot endpoints
# ──────────────────────────────────────────────────────────────────────────────

def spot_ping() -> bool:
    try:
        r = CLIENT.get(f"{BASE}/api/v3/ping", timeout=3.0)
        return r.status_code == 200
    except:
        return False

def spot_balance() -> List[Dict[str, Any]]:
    r = _request("GET", "/api/v3/account", signed=True)
    j = r.json()
    return j.get("balances", [])

def spot_price(symbol: str) -> Optional[float]:
    try:
        r = _request("GET", "/api/v3/ticker/price", params={"symbol": symbol.upper()})
        px = float(r.json().get("price") or 0)
        return px if px > 0 else None
    except:
        return None

__all__ = [
    "spot_ping", "spot_balance", "spot_price"
]
