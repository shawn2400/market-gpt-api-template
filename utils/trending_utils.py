# utils/trending_utils.py
import os
import logging
import time
from typing import List, Optional
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# ---------- Tunables (אפשר דרך ENV) ----------
TRENDING_TOP_N            = int(os.getenv("TRENDING_TOP_N", "30"))
TRENDING_MIN_PRICE        = float(os.getenv("TRENDING_MIN_PRICE", "0.0001"))
TRENDING_TIMEOUT_SEC      = float(os.getenv("TRENDING_TIMEOUT_SEC", "8.0"))
TRENDING_RETRIES          = int(os.getenv("TRENDING_RETRIES", "4"))
TRENDING_BACKOFF_BASE     = float(os.getenv("TRENDING_BACKOFF_BASE", "0.6"))
TRENDING_STATUS_FORCELIST = (403, 418, 429, 500, 502, 503, 504)

_HEADERS = {
    "User-Agent": "AlgoGPT/2 (Render) trending-utils",
    "Accept": "application/json",
    "Accept-Encoding": "gzip",
}

BINANCE_FUTURES_24H = "https://fapi.binance.com/fapi/v1/ticker/24hr"
BINANCE_SPOT_24H    = "https://api.binance.com/api/v3/ticker/24hr"

_session = requests.Session()
_session.trust_env = True  # מאפשר HTTP(S)_PROXY אם קיים בסביבה
_retry = Retry(
    total=TRENDING_RETRIES,
    connect=TRENDING_RETRIES,
    read=TRENDING_RETRIES,
    status=TRENDING_RETRIES,
    backoff_factor=TRENDING_BACKOFF_BASE,
    status_forcelist=list(TRENDING_STATUS_FORCELIST),
    allowed_methods=frozenset(["GET", "HEAD", "OPTIONS"]),
    raise_on_status=False,
)
_adapter = HTTPAdapter(max_retries=_retry, pool_connections=20, pool_maxsize=20)
_session.mount("https://", _adapter)
_session.mount("http://", _adapter)

def _is_html(body: str) -> bool:
    if not body:
        return False
    b = body.strip().upper()
    return "<HTML" in b or "CLOUDFRONT" in b or "CLOUDFLARE" in b

def _fetch_24h(url: str, timeout: float = TRENDING_TIMEOUT_SEC, retries: int = TRENDING_RETRIES, backoff: float = TRENDING_BACKOFF_BASE) -> list:
    last = None
    for attempt in range(retries + 1):
        try:
            r = _session.get(url, headers=_HEADERS, timeout=timeout)
            if r.status_code == 200:
                try:
                    data = r.json()
                    return data if isinstance(data, list) else []
                except Exception as e:
                    logging.warning(f"[trending] JSON parse error: {e}; len={len(r.text or '')}")
                    return []
            if r.status_code in TRENDING_STATUS_FORCELIST:
                # ייתכן html מ־WAF/CloudFront — נתרגם ל-retry ידני מהיר
                if _is_html(r.text):
                    logging.warning(f"[trending] WAF/HTML (http={r.status_code}) — retry light")
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
            last = str(e)
    if last:
        logging.error(f"[trending] failed after retries: {last[:200]}")
    return []

def _pick_usdt_symbols(rows: list, top_n: int, min_price: float = TRENDING_MIN_PRICE) -> List[str]:
    """
    בוחר זוגות USDT עם נפח קוֹט תחרותי. מסנן מחירים מיקרוסקופיים כדי להימנע מזוגות רדומים/לא סחירים.
    """
    scored: List[tuple[str, float]] = []
    for row in rows or []:
        try:
            sym = str(row.get("symbol", "")).upper()
            if not sym.endswith("USDT"):
                continue
            # שדות משותפים ל-SPOT/FUTURES
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
            seen.add(sym)
            out.append(sym)
        if len(out) >= top_n:
            break
    return out

def get_trending_symbols(source: str = "binance24h", market: str = "futures", top_n: Optional[int] = None) -> List[str]:
    """
    מקור דיפולטי: Binance 24h. אם FUTURES נכשל — ננסה SPOT, ולהיפך.
    """
    n = int(top_n or TRENDING_TOP_N)
    market_l = (market or "futures").lower()
    src_l = (source or "binance24h").lower()

    rows = []
    if src_l == "binance24h" and market_l == "futures":
        rows = _fetch_24h(BINANCE_FUTURES_24H)
        if not rows:
            logging.warning("[trending] futures rows empty → trying spot")
            rows = _fetch_24h(BINANCE_SPOT_24H)
    elif src_l in ("binance24h", "spot24h"):
        rows = _fetch_24h(BINANCE_SPOT_24H)
        if not rows:
            logging.warning("[trending] spot rows empty → trying futures")
            rows = _fetch_24h(BINANCE_FUTURES_24H)
    else:
        rows = _fetch_24h(BINANCE_FUTURES_24H)

    syms = _pick_usdt_symbols(rows, top_n=n)
    if not syms:
        logging.warning("[trending] fallback symbols used")
        syms = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT"]
    return syms



































































































































































































































































































































































































