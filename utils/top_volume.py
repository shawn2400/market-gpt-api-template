# utils/top_volume.py
# =========================
# Utility: שליפת Top Volume Symbols מ־Binance (Spot/Futures)
# כולל סינון לפי Quote + Volume מינימלי
# =========================

from __future__ import annotations
import os
from typing import Tuple, List, Dict, Any
import requests
import logging

logger = logging.getLogger("algogpt.top_volume")

# ✅ Endpoints (עם אפשרות override ב־.env)
_FAPI = os.getenv("BINANCE_FUTURES_HTTP_BASE", "https://fapi.binance.com").rstrip("/")
_SAPI = os.getenv("BINANCE_SPOT_HTTP_BASE", "https://api.binance.com").rstrip("/")

# ✅ Session משותף (Connection Pool)
_S = requests.Session()
_S.trust_env = False
_S.headers.update({
    "User-Agent": "AlgoGPT/2 top-volume",
    "Accept": "application/json"
})


def get_top_volume_symbols(
    market: str = "futures",
    quote: str = "USDT",
    limit: int = 50,
    min_quote_volume: float = 0.0
) -> Tuple[bool, List[Dict[str, Any]]]:
    """
    מחזיר סימבולים ממיונים לפי quoteVolume (24h).
    - שוק: futures / spot
    - מחזיר גם symbol וגם quoteVolume
    - מוגן משגיאות רשת (מחזיר False, [])
    """
    try:
        url = (
            f"{_FAPI}/fapi/v1/ticker/24hr"
            if market == "futures"
            else f"{_SAPI}/api/v3/ticker/24hr"
        )
        r = _S.get(url, timeout=10)
        r.raise_for_status()
        data = r.json()

        rows: List[Dict[str, Any]] = []
        # ✅ מינימום Volume מה־env או מהפרמטר
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

            rows.append({
                "symbol": sym,
                "quoteVolume": qv
            })

        # ✅ מיון לפי נפח
        rows.sort(key=lambda t: t["quoteVolume"], reverse=True)

        return True, rows[: int(limit)]

    except Exception as e:
        logger.warning(f"get_top_volume_symbols failed: {e}")
        return False, []








