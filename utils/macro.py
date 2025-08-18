# utils/macro.py
from __future__ import annotations
from typing import Dict, Any, Optional, List
import os, time
import requests

__all__ = ["macro_snapshot", "fred_last_value", "fred_series_yoy"]

_S = requests.Session()
_S.trust_env = False
_S.headers.update({
    "User-Agent": "AlgoGPT/2 macro",
    "Accept": "application/json",
    "Accept-Encoding": "gzip",
})

def _get_json(url: str, params: Optional[Dict[str, Any]] = None, timeout: float = 10.0) -> Optional[dict]:
    try:
        r = _S.get(url, params=params, timeout=timeout)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return None

# --------- Yahoo (quotes) / Free public sources ---------

def _yahoo_quote(symbol: str) -> Optional[float]:
    j = _get_json(f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}", params={"range":"1d","interval":"5m"})
    try:
        close = j["chart"]["result"][0]["indicators"]["quote"][0]["close"][-1]
        return float(close) if close is not None else None
    except Exception:
        return None

def _fear_greed() -> Optional[int]:
    j = _get_json("https://api.alternative.me/fng/", params={"limit":1})
    try:
        return int(j["data"][0]["value"])
    except Exception:
        return None

def _btc_dominance() -> Optional[float]:
    j = _get_json("https://api.coingecko.com/api/v3/global")
    try:
        return float(j["data"]["market_cap_percentage"]["btc"])
    except Exception:
        return None

# --------- FRED helpers ---------

def fred_observations(series_id: str, limit: int = 24) -> List[Dict[str, Any]]:
    """
    מחזיר רשימת observations (תאריך/ערך) מסדרה של FRED.
    דורש FRED_API_KEY; אם חסר – מחזיר [].
    """
    api_key = os.getenv("FRED_API_KEY", "")
    if not api_key:
        return []
    params = {
        "series_id": series_id,
        "api_key": api_key,
        "file_type": "json",
        "sort_order": "desc",
        "limit": int(limit),
    }
    j = _get_json("https://api.stlouisfed.org/fred/series/observations", params=params) or {}
    return j.get("observations") or []

def fred_last_value(series_id: str) -> Optional[float]:
    obs = fred_observations(series_id, limit=1)
    if not obs:
        return None
    try:
        v = obs[0]["value"]
        return float(v) if v not in (".", "", None) else None
    except Exception:
        return None

def fred_series_yoy(series_id: str) -> Optional[float]:
    """
    מחשב שינוי YoY (%) על פי 13 נקודות חודשיות אחרונות (כולל נוכחי).
    """
    obs = fred_observations(series_id, limit=14)
    vals: List[float] = []
    for o in obs:
        v = o.get("value")
        try:
            vf = float(v)
            vals.append(vf)
        except Exception:
            continue
        if len(vals) >= 13:
            break
    if len(vals) < 13:
        return None
    cur, prev = vals[0], vals[12]  # Desc sorted (האחרון ראשון)
    if prev == 0:
        return None
    return float((cur - prev) / prev * 100.0)

# --------- Snapshot aggregator ---------

def macro_snapshot() -> Dict[str, Any]:
    """
    מחזיר תמונת מצב קצרה:
      - DXY, NDX, SPX (Yahoo)
      - BTC dominance (CoinGecko), Fear & Greed (Alternative.me)
      - CPI YoY (CPIAUCSL), Unemployment (UNRATE), M2 YoY (WM2NS) — מ־FRED אם יש מפתח
    """
    # שוק
    dxy = _yahoo_quote("DX-Y.NYB") or _yahoo_quote("DX-Y.NYB")   # נסיון כפול
    ndx = _yahoo_quote("^NDX")
    spx = _yahoo_quote("^GSPC")
    fg  = _fear_greed()
    dom = _btc_dominance()

    # FRED (אופציונלי)
    cpi_yoy   = fred_series_yoy("CPIAUCSL")
    unrate    = fred_last_value("UNRATE")     # כבר באחוזים
    m2_yoy    = fred_series_yoy("WM2NS")      # M2 (לא מנורמל), YoY%

    return {
        "ok": True,
        "market": {
            "dxy": dxy,
            "nasdaq_100": ndx,
            "sp500": spx,
            "btc_dominance_pct": dom,
            "fear_greed": fg,
        },
        "macro": {
            "cpi_yoy_pct": cpi_yoy,
            "unemployment_pct": unrate,
            "m2_yoy_pct": m2_yoy,
        },
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "note": None if os.getenv("FRED_API_KEY") else "FRED_API_KEY missing – macro fields may be None",
    }


