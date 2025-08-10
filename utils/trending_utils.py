# utils/trending_utils.py
import logging
from typing import List, Optional
import time
import requests

from utils import config

BINANCE_FUTURES_24H = getattr(config, "BINANCE_FUTURES_HTTP_BASE", "https://fapi.binance.com") + "/fapi/v1/ticker/24hr"
BINANCE_SPOT_24H    = getattr(config, "BINANCE_SPOT_HTTP_BASE", "https://api.binance.com") + "/api/v3/ticker/24hr"

_UA = {"User-Agent": "AlgoGPT/2 (Render) trending_utils", "Accept": "application/json"}

def _fetch_24h(url: str, timeout: float = 8.0, retries: int = 3, backoff: float = 0.6) -> list:
    last_err: Optional[Exception] = None
    for attempt in range(retries + 1):
        try:
            r = requests.get(url, timeout=timeout, headers=_UA)
            if r.status_code == 200:
                data = r.json()
                return data if isinstance(data, list) else []
            if r.status_code in (403, 418, 429, 503):
                d = min(10.0, backoff * (2 ** attempt))
                logging.warning(f"[trending] http={r.status_code} {url} → sleep {d:.2f}s")
                time.sleep(d); continue
            r.raise_for_status()
        except Exception as e:
            last_err = e
            d = min(10.0, backoff * (2 ** attempt))
            logging.warning(f"[trending] fetch failed (attempt {attempt+1}/{retries+1}) {url}: {e} → {d:.2f}s")
            time.sleep(d)
    if last_err:
        logging.warning(f"[trending] final failure: {last_err}")
    return []

def _pick_usdt_symbols(rows: list, top_n: int) -> List[str]:
    """
    בוחר USDT בלבד, לפי quoteVolume/price חיוביים, מסנן נזילות נמוכה.
    """
    scored = []
    for row in rows:
        try:
            sym = str(row.get("symbol", "")).upper()
            if not sym.endswith("USDT"):
                continue
            qv = float(row.get("quoteVolume") or 0.0)
            price = float(row.get("lastPrice") or 0.0)
            if qv <= 0 or price <= 0:
                continue
            scored.append((sym, qv))
        except Exception:
            continue
    scored.sort(key=lambda x: x[1], reverse=True)
    out, seen = [], set()
    for sym, _ in scored:
        if sym not in seen:
            seen.add(sym); out.append(sym)
        if len(out) >= top_n:
            break
    return out

def get_trending_symbols(source: str = "binance24h", market: str = "futures", top_n: int = 30) -> List[str]:
    """
    מחזיר רשימת סימבולים טרנדיים. סינכרוני.
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

































































































































































































































































































































































































