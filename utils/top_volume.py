# utils/top_volume.py
# =========================
# Utility למשיכת Top Volume Symbols מ-Binance
# כולל Cache פנימי כדי להקטין עומס על Binance API
# =========================

from __future__ import annotations
import os, time, json
from typing import Tuple, List, Dict
import requests
from pathlib import Path

_FAPI = os.getenv("BINANCE_FUTURES_HTTP_BASE", "https://fapi.binance.com")
_SAPI = os.getenv("BINANCE_SPOT_HTTP_BASE", "https://api.binance.com")

_S = requests.Session()
_S.trust_env = False
_S.headers.update({"User-Agent": "AlgoGPT/2 top-volume", "Accept": "application/json"})

# Cache מקומי (למניעת עומס)
CACHE_FILE = Path("static/cache/top_volume.json")
CACHE_TTL = int(os.getenv("TOP_VOLUME_CACHE_TTL", "30"))  # שניות

def _load_cache() -> Dict:
    if CACHE_FILE.exists():
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def _save_cache(data: Dict):
    try:
        CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f)
    except Exception:
        pass


def get_top_volume_symbols(
    market: str = "futures",
    quote: str = "USDT",
    limit: int = 50,
    min_quote_volume: float = 0.0
) -> Tuple[bool, List[Dict[str, any]]]:
    """
    מחזיר סימבולים ממיונים לפי quoteVolume (24h).
    כולל שימוש ב-Cache כדי להוריד עומס.
    """
    cache = _load_cache()
    now = time.time()
    key = f"{market}:{quote}:{limit}:{min_quote_volume}"

    if key in cache and now - cache[key]["ts"] < CACHE_TTL:
        return True, cache[key]["symbols"]

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
        symbols = [{"symbol": s, "quoteVolume": v} for s, v in rows[: int(limit)]]

        # שמירה ב-Cache
        cache[key] = {"ts": now, "symbols": symbols}
        _save_cache(cache)

        return True, symbols
    except Exception:
        return False, []







