# utils/trending_utils.py
import logging
from typing import List
import requests

BINANCE_FUTURES_24H = "https://fapi.binance.com/fapi/v1/ticker/24hr"
BINANCE_SPOT_24H = "https://api.binance.com/api/v3/ticker/24hr"

def _fetch_24h(url: str, timeout: float = 8.0) -> list:
    try:
        r = requests.get(url, timeout=timeout)
        r.raise_for_status()
        data = r.json()
        if isinstance(data, list):
            return data
        return []
    except Exception as e:
        logging.warning(f"[trending] fetch 24h failed: {e}")
        return []

def _pick_usdt_symbols(rows: list, top_n: int) -> List[str]:
    """
    בוחר USDT בלבד, לפי quoteVolume/volume, מסנן נזילות נמוכה.
    """
    scored = []
    for row in rows:
        try:
            sym = str(row.get("symbol", "")).upper()
            if not sym.endswith("USDT"):
                continue
            # ב־Futures יש "quoteVolume"; ב־Spot גם.
            qv = float(row.get("quoteVolume") or 0.0)
            price = float(row.get("lastPrice") or 0.0)
            if qv <= 0 or price <= 0:
                continue
            scored.append((sym, qv))
        except Exception:
            continue
    scored.sort(key=lambda x: x[1], reverse=True)
    # שמור על ייחוד
    out, seen = [], set()
    for sym, _ in scored:
        if sym not in seen:
            seen.add(sym)
            out.append(sym)
        if len(out) >= top_n:
            break
    return out

def get_trending_symbols(source: str = "binance24h", market: str = "futures", top_n: int = 30) -> List[str]:
    """
    מחזיר רשימת סימבולים טרנדיים. סינכרוני (תואם לשימוש הנוכחי).
    source: "binance24h" (מומלץ), "spot24h"
    """
    rows = []
    if source == "binance24h" and market.lower() == "futures":
        rows = _fetch_24h(BINANCE_FUTURES_24H)
    elif source in ("binance24h", "spot24h"):
        rows = _fetch_24h(BINANCE_SPOT_24H)
    else:
        rows = _fetch_24h(BINANCE_FUTURES_24H)

    syms = _pick_usdt_symbols(rows, top_n=top_n)
    if not syms:
        logging.warning("[trending] fallback symbols used")
        syms = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT"]
    return syms
































































































































































































































































































































































































