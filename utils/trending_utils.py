# utils/trending_utils.py
import logging
import time
from typing import List, Optional
import requests

_HEADERS = {
    "User-Agent": "AlgoGPT/2 (Render) trending-utils",
    "Accept": "application/json",
    "Accept-Encoding": "gzip",
}

BINANCE_FUTURES_24H = "https://fapi.binance.com/fapi/v1/ticker/24hr"
BINANCE_SPOT_24H    = "https://api.binance.com/api/v3/ticker/24hr"

def _fetch_24h(url: str, timeout: float = 8.0, retries: int = 4, backoff: float = 0.6) -> list:
    last = None
    for attempt in range(retries + 1):
        try:
            r = requests.get(url, headers=_HEADERS, timeout=timeout)
            if r.status_code == 200:
                data = r.json()
                return data if isinstance(data, list) else []
            if r.status_code in (403, 418, 429, 503):
                d = min(10.0, backoff * (2 ** attempt))
                logging.warning(f"[trending] http={r.status_code} → sleep {d:.2f}s (attempt {attempt+1}/{retries+1})")
                time.sleep(d)
                last = r.text
                continue
            r.raise_for_status()
        except Exception as e:
            d = min(10.0, backoff * (2 ** attempt))
            logging.warning(f"[trending] network error → sleep {d:.2f}s (attempt {attempt+1}/{retries+1}): {e}")
            time.sleep(d)
            last = e
    if last:
        logging.error(f"[trending] failed after retries: {last}")
    return []

def _pick_usdt_symbols(rows: list, top_n: int, min_price: float = 0.0001) -> List[str]:
    scored = []
    for row in rows:
        try:
            sym = str(row.get("symbol", "")).upper()
            if not sym.endswith("USDT"):
                continue
            qv = float(row.get("quoteVolume") or 0.0)
            price = float(row.get("lastPrice") or 0.0)
            if qv <= 0 or price < min_price:
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


































































































































































































































































































































































































