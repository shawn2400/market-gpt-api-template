# utils/macro.py
from __future__ import annotations
from typing import Dict, Any, Optional
import time, requests

_S = requests.Session()
_S.trust_env = False
_S.headers.update({"User-Agent": "AlgoGPT/2 macro"})

def _get(url: str, timeout: float = 7.0):
    try:
        r = _S.get(url, timeout=timeout)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return None

def macro_snapshot() -> Dict[str, Any]:
    """
    דוגם נתונים זמינים ללא מפתחות:
      - Fear & Greed (alternative.me)
      - BTC dominance (coingecko global)
    שדות שאינם זמינים ללא API key מוחזרים כ-None.
    """
    fear, btc_dom = None, None
    fg = _get("https://api.alternative.me/fng/?limit=1")
    if fg and isinstance(fg.get("data"), list) and fg["data"]:
        try:
            fear = int(fg["data"][0]["value"])
        except Exception:
            pass

    cg = _get("https://api.coingecko.com/api/v3/global")
    if cg and "data" in cg:
        try:
            btc_dom = float(cg["data"]["market_cap_percentage"]["btc"])
        except Exception:
            pass

    # DXY/NDX/SPX דורשים מקורות עם מפתח (FRED/Quandl/Polygon). נשאיר None.
    return {
        "ok": True,
        "dxy": None,
        "ndx": None,
        "spx": None,
        "btc_dominance": btc_dom,
        "fear_greed": fear,
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "note": "DXY/NDX/SPX omitted (requires paid API)."
    }

