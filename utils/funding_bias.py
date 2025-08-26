# utils/funding_bias.py
from __future__ import annotations
import os, time, json
from typing import Optional, Tuple
import httpx

try:
    from utils.redis_client import redis_client as RED
except Exception:
    RED = None

BASE = os.getenv("BINANCE_FUTURES_HTTP_BASE", "https://fapi.binance.com")
TTL  = int(float(os.getenv("FUNDING_TTL_SEC","1800")))  # 30 דקות

def _key(sym: str) -> str:
    return f"algogpt:funding:{sym.upper()}"

def fetch_funding(sym: str) -> Optional[Tuple[float,int]]:
    """
    מחזיר (rate, ts_ms) או None.
    """
    url = f"{BASE}/fapi/v1/fundingRate"
    try:
        with httpx.Client(timeout=6) as c:
            r = c.get(url, params={"symbol": sym.upper(), "limit": 1})
            if r.status_code != 200: return None
            arr = r.json()
            if not isinstance(arr, list) or not arr: return None
            it = arr[0]
            rate = float(it.get("fundingRate"))
            ts   = int(it.get("fundingTime"))
            return rate, ts
    except Exception:
        return None

def get_funding_cached(sym: str) -> Optional[Tuple[float,int]]:
    if RED:
        try:
            raw = RED.get(_key(sym))
            if raw:
                j = json.loads(raw)
                return float(j["rate"]), int(j["ts"])
        except Exception:
            pass
    # miss → fetch
    val = fetch_funding(sym)
    if val and RED:
        try:
            RED.set(_key(sym), json.dumps({"rate": val[0], "ts": val[1]}), ex=TTL)
        except Exception:
            pass
    return val

def funding_bias_for_side(sym: str, side: str) -> float:
    """
    side: LONG/SHORT
    מחזיר עוצמת הטיה [-1..+1] לטובת/נגד הכיוון (חיובי = תומך בטרייד).
    לוגיקה:
      * rate > +X% → עדיף SHORT (שלילי ל-LONG)
      * rate < -X% → עדיף LONG  (שלילי ל-SHORT)
    ENV:
      FUNDING_STRONG_PCT (דיפולט 0.03% = 0.0003)
      FUNDING_MAX_BIAS (דיפולט 0.25)
    """
    thr  = float(os.getenv("FUNDING_STRONG_PCT","0.0003"))
    cap  = float(os.getenv("FUNDING_MAX_BIAS","0.25"))
    v = get_funding_cached(sym)
    if not v: return 0.0
    rate = v[0]  # e.g. 0.0001 = 0.01%
    # סימן: חיובי → יקר להחזיק LONG; שלילי → יקר להחזיק SHORT
    bias = 0.0
    if rate >= thr:
        # נוטה נגד LONG, בעד SHORT
        bias = -min(cap, rate/thr * cap) if side.upper()=="LONG" else +min(cap, rate/thr * cap)
    elif rate <= -thr:
        # נוטה נגד SHORT, בעד LONG
        bias = +min(cap, abs(rate)/thr * cap) if side.upper()=="LONG" else -min(cap, abs(rate)/thr * cap)
    return bias
