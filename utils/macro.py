# utils/macro.py
from __future__ import annotations
import time, os
from typing import Dict, Any, Optional
import requests

_S = requests.Session()
_S.trust_env = False
_S.headers.update({
    "User-Agent": "AlgoGPT/2 macro",
    "Accept": "application/json",
    "Accept-Encoding": "gzip",
})

def _get_json(url: str, timeout: float = 8.0) -> Optional[dict]:
    try:
        r = _S.get(url, timeout=timeout)
        if r.status_code == 200:
            return r.json()
        if r.status_code in (429, 500, 502, 503, 504):
            time.sleep(0.7)
            r2 = _S.get(url, timeout=timeout)
            if r2.status_code == 200:
                return r2.json()
    except Exception:
        pass
    return None

def _yahoo_quote(symbol: str) -> Optional[float]:
    # Yahoo Finance chart API
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range=1d&interval=5m"
    j = _get_json(url)
    try:
        close = j["chart"]["result"][0]["indicators"]["quote"][0]["close"][-1]
        return float(close) if close is not None else None
    except Exception:
        return None

def _fear_greed() -> Optional[int]:
    # Alternative.me F&G
    j = _get_json("https://api.alternative.me/fng/?limit=1")
    try:
        v = j["data"][0]["value"]
        return int(v)
    except Exception:
        return None

def _btc_dominance() -> Optional[float]:
    # CoinGecko global
    j = _get_json("https://api.coingecko.com/api/v3/global")
    try:
        return float(j["data"]["market_cap_percentage"]["btc"])
    except Exception:
        return None

def macro_snapshot() -> Dict[str, Any]:
    dxy = _yahoo_quote("DX-Y.NYB") or _yahoo_quote("DX-Y.NYB")  # נסיון כפול
    ndx = _yahoo_quote("^NDX")
    spx = _yahoo_quote("^GSPC")
    fg  = _fear_greed()
    dom = _btc_dominance()
    return {
        "ok": True,
        "dxy": dxy, "ndx": ndx, "spx": spx,
        "btc_dominance": dom,
        "fear_greed": fg,
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "note": None,
    }

