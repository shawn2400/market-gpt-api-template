# utils/top_volume.py
from __future__ import annotations
import os
from typing import Tuple, List
import requests

_FAPI = os.getenv("BINANCE_FUTURES_HTTP_BASE", "https://fapi.binance.com")
_SAPI = os.getenv("BINANCE_SPOT_HTTP_BASE", "https://api.binance.com")

_S = requests.Session()
_S.trust_env = False
_S.headers.update({"User-Agent": "AlgoGPT/2 top-volume", "Accept": "application/json"})

def get_top_volume_symbols(
    *, market: str = "futures", quote: str = "USDT", limit: int = 50, min_quote_volume: float = 0.0
) -> Tuple[bool, List[str]]:
    """
    מחזיר סימבולים ממיונים לפי quoteVolume (24h). לא נכשל על שגיאת רשת — יחזיר (False, []).
    """
    try:
        url = f"{_FAPI}/fapi/v1/ticker/24hr" if market == "futures" else f"{_SAPI}/api/v3/ticker/24hr"
        r = _S.get(url, timeout=10)
        r.raise_for_status()
        data = r.json()
        rows: List[tuple[str, float]] = []
        min_qv_env = float(os.getenv("TOP_VOLUME_MIN_QV", "0") or 0.0)
        mql = max(float(min_quote_volume or 0.0), min_qv_env)

        for item in data:
            sym = (item.get("symbol") or "").upper()
            if not sym.endswith(quote.upper()):
                continue
            try:
                qv = float(item.get("quoteVolume") or 0.0)
            except Exception:
                qv = 0.0
            if qv < mql:
                continue
            rows.append((sym, qv))
        rows.sort(key=lambda t: t[1], reverse=True)
        return True, [s for s, _ in rows[: int(limit)]]
    except Exception:
        return False, []







