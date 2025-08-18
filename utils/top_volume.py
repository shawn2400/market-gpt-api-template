# utils/top_volume.py
from __future__ import annotations
import os
import time
from typing import List, Tuple

import requests

FUTURES_BASE = os.getenv("BINANCE_FUTURES_HTTP_BASE", "https://fapi.binance.com")
SPOT_BASE    = os.getenv("BINANCE_SPOT_HTTP_BASE",    "https://api.binance.com")
ENV_MIN_QV   = float(os.getenv("TOP_VOLUME_MIN_QV", "0"))

__all__ = ["get_top_volume_symbols"]

_S = requests.Session()
_S.trust_env = False
_S.headers.update({
    "User-Agent": "AlgoGPT/2 top-volume",
    "Accept": "application/json",
    "Accept-Encoding": "gzip",
})

# זיכרון מטמון פשוט כדי לא לרסק את ה־API בכל קריאה חוזרת בתוך חלון קצר
_cache: dict = {"t": 0.0, "key": "", "data": []}

def _get_json(url: str, timeout: float = 8.0):
    r = _S.get(url, timeout=timeout)
    r.raise_for_status()
    return r.json()

def get_top_volume_symbols(
    market: str = "futures",
    quote: str = "USDT",
    limit: int = 50,
    min_quote_volume: float | None = None,
    cache_ttl: float = 10.0,
) -> Tuple[bool, List[str]]:
    """
    מחזיר (ok, symbols) ממוין לפי 24h quoteVolume (יורד) לסימבולים שמסתיימים ב־`quote`.
    מכבד TOP_VOLUME_MIN_QV אם `min_quote_volume` לא הועבר.
    יש מטמון פנימי (cache_ttl שניות) להפחתת עומס.
    """
    try:
        eff_min_qv = ENV_MIN_QV if (min_quote_volume is None) else float(min_quote_volume)

        # Cache key בהתאם לפרמטרים
        key = f"{market}:{quote}:{int(limit)}:{eff_min_qv:.6f}"
        now = time.monotonic()
        if _cache["key"] == key and (now - _cache["t"] <= cache_ttl):
            return True, list(_cache["data"])

        # שליפת הטיקר לפי מרקט
        if market == "futures":
            arr = _get_json(f"{FUTURES_BASE}/fapi/v1/ticker/24hr")
        elif market == "spot":
            arr = _get_json(f"{SPOT_BASE}/api/v3/ticker/24hr")
        else:
            # מרקט לא נתמך
            return False, []

        # סינון לפי quote
        rows = [x for x in arr if str(x.get("symbol", "")).endswith(quote)]

        # מיון לפי נפח קוֹוט 24ש׳
        rows.sort(key=lambda x: float(x.get("quoteVolume", 0.0)), reverse=True)

        # סף מינימלי אם הוגדר
        if eff_min_qv > 0:
            rows = [x for x in rows if float(x.get("quoteVolume", 0.0)) >= eff_min_qv]

        syms = [str(x.get("symbol")) for x in rows[: int(limit)] if "symbol" in x]

        # עדכון מטמון
        _cache.update({"t": now, "key": key, "data": syms})
        return True, syms

    except Exception:
        # לא מפילים את השרת אם יש כשל חיצוני/רשת—פשוט מחזירים (False, [])
        return False, []





