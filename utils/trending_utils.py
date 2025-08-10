# utils/trending_utils.py
import logging
from typing import List, Optional
import requests
import time
import random

from utils import config

# REST ישיר (עוקף ספריה) – יותר גמיש למקרי 403/RateLimit הקודמים
FAPI_24HR = "https://fapi.binance.com/fapi/v1/ticker/24hr"
SPOT_24HR = "https://api.binance.com/api/v3/ticker/24hr"

def _retry_get_json(url: str, max_retries: int = 4, base_backoff: float = 0.6, timeout: int = 8) -> Optional[List[dict]]:
    last_exc = None
    for attempt in range(max_retries + 1):
        try:
            r = requests.get(url, timeout=timeout, headers={"User-Agent": "AlgoGPT/1.0 (+render)"})
            if r.status_code == 200:
                return r.json()
            if r.status_code in (418, 429, 403, 503):
                delay = base_backoff * (2 ** attempt) + random.uniform(0, 0.25)
                logging.warning(f"[trending] HTTP {r.status_code} {url} attempt {attempt+1}/{max_retries+1} → sleep {delay:.2f}s")
                time.sleep(delay); continue
            logging.warning(f"[trending] HTTP {r.status_code} {url} (no retry)")
            break
        except Exception as e:
            last_exc = e
            delay = base_backoff * (2 ** attempt) + random.uniform(0, 0.25)
            logging.warning(f"[trending] net error {url} attempt {attempt+1}/{max_retries+1} → sleep {delay:.2f}s: {e}")
            time.sleep(delay)
    if last_exc:
        logging.error(f"[trending] exhausted retries: {last_exc}")
    return None

def _top_usdt_symbols(rows: List[dict], top_n: int = 50) -> List[str]:
    # דירוג לפי quoteVolume (מספרי) והחזר סמלי USDT
    def _to_float(x):
        try: return float(x)
        except: return 0.0
    pairs = []
    for d in rows:
        try:
            sym = str(d.get("symbol", ""))
            if not sym.endswith("USDT"):
                continue
            vol = _to_float(d.get("quoteVolume", d.get("volume", 0)))
            pairs.append((sym, vol))
        except Exception:
            continue
    pairs.sort(key=lambda x: x[1], reverse=True)
    # החזר ללא כפילות, עד top_n
    out = []
    seen = set()
    for sym, _ in pairs:
        if sym not in seen:
            seen.add(sym); out.append(sym)
        if len(out) >= top_n:
            break
    return out

def get_trending_symbols(source: str = "coingecko", market: str = "futures", top_n: int = 50) -> List[str]:
    """
    מחזיר רשימת סמלים "חמים" לשרת:
    - בפועל משתמש ב-Binance 24hr לפי market (Futures/Spot) בגלל זמינות/אמינות.
    - source נשמר לפרמטר עתידי (כדי לא לשבור חתימות); כיום מתעלמים ממנו.
    """
    try:
        url = FAPI_24HR if str(market).lower() == "futures" else SPOT_24HR
        data = _retry_get_json(url, max_retries=int(config.BINANCE_MAX_RETRIES), base_backoff=float(config.BINANCE_BACKOFF_BASE))
        if isinstance(data, list) and data:
            syms = _top_usdt_symbols(data, top_n=top_n)
            if syms:
                logging.info(f"[trending] selected {len(syms)} symbols (top {top_n}) from {url}")
                return syms
        logging.warning("[trending] empty/invalid 24hr data, using fallback")
        return ["BTCUSDT", "ETHUSDT", "BNBUSDT"]
    except Exception as e:
        logging.warning(f"[trending] error: {e}")
        return ["BTCUSDT", "ETHUSDT", "BNBUSDT"]
































































































































































































































































































































































































