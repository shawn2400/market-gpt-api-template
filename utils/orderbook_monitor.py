# utils/orderbook_monitor.py
from __future__ import annotations
import os, math, logging, time
from typing import Dict, Any, List, Tuple, Optional
import httpx

logger = logging.getLogger("algogpt.orderbook")

BINANCE_FUTURES_HTTP_BASE = os.getenv("BINANCE_FUTURES_HTTP_BASE", "https://fapi.binance.com").rstrip("/")
BINANCE_SPOT_HTTP_BASE    = os.getenv("BINANCE_SPOT_HTTP_BASE", "https://api.binance.com").rstrip("/")
HTTP_TIMEOUT              = float(os.getenv("BINANCE_HTTP_TIMEOUT", "8.0"))
DEFAULT_LIMIT             = int(os.getenv("ORDERBOOK_DEPTH_LIMIT", "50"))  # רשות; אם לא ב-ENV → 50
IMBALANCE_MIN_DEFAULT     = float(os.getenv("ORDERBOOK_IMBALANCE_MIN", "0.15"))

_client: httpx.Client | None = None
_cache: Dict[str, Tuple[float, Dict[str, Any]]] = {}  # key -> (ts, data)
_CACHE_TTL_SEC = 1.5  # קצרצר

def _get_client() -> httpx.Client:
    global _client
    if _client is None:
        _client = httpx.Client(timeout=HTTP_TIMEOUT)
    return _client

def _endpoint(market: str) -> str:
    if (market or "").lower().strip() == "spot":
        return f"{BINANCE_SPOT_HTTP_BASE}/api/v3/depth"
    return f"{BINANCE_FUTURES_HTTP_BASE}/fapi/v1/depth"

def fetch_orderbook(symbol: str, *, limit: int | None = None, market: str = "futures") -> Dict[str, Any]:
    """
    שולף עומק ספר הפקודות. מחזיר dict: { ok, symbol, lastUpdateId, bids, asks, error? }
    """
    s = symbol.upper().strip()
    lim = int(limit or DEFAULT_LIMIT)
    key = f"{market}:{s}:{lim}"
    now = time.time()

    # cache קצר
    hit = _cache.get(key)
    if hit and (now - hit[0] <= _CACHE_TTL_SEC):
        return hit[1]

    url = _endpoint(market)
    try:
        r = _get_client().get(url, params={"symbol": s, "limit": lim})
        r.raise_for_status()
        data = r.json()
        out = {
            "ok": True,
            "symbol": s,
            "lastUpdateId": data.get("lastUpdateId"),
            "bids": data.get("bids") or [],
            "asks": data.get("asks") or [],
        }
        _cache[key] = (now, out)
        return out
    except Exception as e:
        logger.warning("[orderbook] fetch failed %s %s: %s", market, s, e)
        return {"ok": False, "symbol": s, "error": str(e)}

def _sum_side_usd(levels: List[List[Any]]) -> Tuple[float, float, Tuple[float, float]]:
    """
    מחזיר: (total_usd, total_qty, (top_price, top_qty))
    """
    total_usd = 0.0
    total_qty = 0.0
    top_price, top_qty = 0.0, 0.0
    if not levels:
        return 0.0, 0.0, (0.0, 0.0)
    try:
        # רשומות בפורמט ["price","qty",...]
        p0 = float(levels[0][0]); q0 = float(levels[0][1])
        top_price, top_qty = p0, q0
    except Exception:
        pass
    for row in levels:
        try:
            p = float(row[0]); q = float(row[1])
            total_usd += p * q
            total_qty += q
        except Exception:
            continue
    return total_usd, total_qty, (top_price, top_qty)

def analyze_orderbook_pressure(symbol: str, *, limit: int | None = None, market: str = "futures",
                               min_imbalance: float | None = None) -> Dict[str, Any]:
    """
    חישוב לחץ ספר פקודות:
      - bid_usd / ask_usd
      - imbalance = (bid_usd - ask_usd) / (bid_usd + ask_usd)
      - signal: buy/sell/neutral
    """
    ob = fetch_orderbook(symbol, limit=limit, market=market)
    if not ob.get("ok"):
        return {"ok": False, "symbol": symbol.upper(), "error": ob.get("error")}

    bids = ob.get("bids") or []
    asks = ob.get("asks") or []

    b_usd, b_qty, (b_top_p, b_top_q) = _sum_side_usd(bids)
    a_usd, a_qty, (a_top_p, a_top_q) = _sum_side_usd(asks)
    denom = max(b_usd + a_usd, 1e-9)
    imb = (b_usd - a_usd) / denom

    thr = IMBALANCE_MIN_DEFAULT if min_imbalance is None else float(min_imbalance)
    if imb >= thr:
        sig = "buy"
    elif imb <= -thr:
        sig = "sell"
    else:
        sig = "neutral"

    return {
        "ok": True,
        "symbol": symbol.upper(),
        "lastUpdateId": ob.get("lastUpdateId"),
        "bid_usd": b_usd,
        "ask_usd": a_usd,
        "bid_qty": b_qty,
        "ask_qty": a_qty,
        "imbalance": round(imb, 4),
        "signal": sig,
        "top_buy_wall": {"price": b_top_p, "qty": b_top_q, "usd": b_top_p * b_top_q},
        "top_sell_wall": {"price": a_top_p, "qty": a_top_q, "usd": a_top_p * a_top_q},
        "limit": int(limit or DEFAULT_LIMIT),
        "market": market,
    }
