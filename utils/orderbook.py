# utils/orderbook.py
from __future__ import annotations
import os
from typing import Dict, Any, List, Tuple, Optional
import httpx
import math

_FAPI = os.getenv("BINANCE_FUTURES_HTTP_BASE", "https://fapi.binance.com").rstrip("/")
_SPOT = os.getenv("BINANCE_SPOT_HTTP_BASE", "https://api.binance.com").rstrip("/")

_VALID_LIMITS = (5, 10, 20, 50, 100, 500, 1000)

def _safe_float(x) -> float:
    try:
        return float(x)
    except Exception:
        return math.nan

def _round_limit(n: int) -> int:
    n = max(5, min(1000, int(n)))
    if n in _VALID_LIMITS:
        return n
    for opt in _VALID_LIMITS:
        if n <= opt:
            return opt
    return 1000

def _pick_base(market: str) -> str:
    return _SPOT if str(market).lower().startswith("spot") else _FAPI

def fetch_depth(symbol: str, *, limit: int = 100, market: str = "futures", timeout: float = 5.0) -> Dict[str, Any]:
    """
    משיכת עומק (bids/asks) מבינאנס. מחזיר מבנה JSON של Binance depth בתוספת ok/symbol.
    """
    symbol = (symbol or "").upper().strip()
    if not symbol:
        return {"ok": False, "error": "missing_symbol"}
    lim = _round_limit(limit)

    base = _pick_base(market)
    url = f"{base}/fapi/v1/depth" if base == _FAPI else f"{base}/api/v3/depth"

    with httpx.Client(timeout=timeout) as client:
        r = client.get(url, params={"symbol": symbol, "limit": lim})
        r.raise_for_status()
        data = r.json()

    if not isinstance(data, dict) or "bids" not in data or "asks" not in data:
        return {"ok": False, "error": "bad_depth_payload", "symbol": symbol}

    return {"ok": True, "symbol": symbol, "limit": lim, **data}

def _sum_levels(levels: List[List[str]], n: int) -> Tuple[float, float]:
    """
    סכום נומינטיבי (מחיר*כמות) וכמות על פני n רמות.
    """
    n = max(1, min(n, len(levels)))
    notional = 0.0
    qty = 0.0
    for px, q in levels[:n]:
        p = _safe_float(px)
        qq = _safe_float(q)
        if math.isnan(p) or math.isnan(qq):
            continue
        notional += p * qq
        qty += qq
    return notional, qty

def compute_pressure(depth: Dict[str, Any], *, top_levels: int = 20) -> Dict[str, Any]:
    """
    מחשב לחץ קנייה/מכירה ו־imbalance על בסיס n הרמות הראשונות.
    """
    bids = depth.get("bids") or []
    asks = depth.get("asks") or []
    N = max(1, min(top_levels, 1000))

    bid_notional, bid_qty = _sum_levels(bids, N)
    ask_notional, ask_qty = _sum_levels(asks, N)

    total_qty = (bid_qty + ask_qty) or 1.0
    imbalance_qty = (bid_qty - ask_qty) / total_qty

    # מחירי best
    best_bid = _safe_float(bids[0][0]) if bids else math.nan
    best_ask = _safe_float(asks[0][0]) if asks else math.nan
    mid = (best_bid + best_ask) / 2.0 if not (math.isnan(best_bid) or math.isnan(best_ask)) else math.nan
    spread = (best_ask - best_bid) if not (math.isnan(best_bid) or math.isnan(best_ask)) else math.nan
    spread_bps = (spread / mid * 10_000.0) if (not math.isnan(spread) and not math.isnan(mid) and mid > 0) else math.nan

    return {
        "ok": True,
        "levels_used": N,
        "best_bid": None if math.isnan(best_bid) else best_bid,
        "best_ask": None if math.isnan(best_ask) else best_ask,
        "mid": None if math.isnan(mid) else mid,
        "spread": None if math.isnan(spread) else spread,
        "spread_bps": None if math.isnan(spread_bps) else spread_bps,
        "bids": {"qty": bid_qty, "notional": bid_notional},
        "asks": {"qty": ask_qty, "notional": ask_notional},
        "imbalance_qty": imbalance_qty,  # [-1..+1]
        "pressure_side": "BUY" if imbalance_qty > 0 else ("SELL" if imbalance_qty < 0 else "NEUTRAL"),
    }

def get_orderbook_pressure(symbol: str, *, market: str = "futures", limit: int = 100, top_levels: int = 20) -> Dict[str, Any]:
    """
    API נוח: משיכת עומק + חישוב לחץ בריצה אחת.
    """
    d = fetch_depth(symbol, limit=limit, market=market)
    if not d.get("ok"):
        return {"ok": False, "symbol": symbol.upper(), "error": d.get("error", "depth_failed")}
    p = compute_pressure(d, top_levels=top_levels)
    return {"ok": True, "symbol": d.get("symbol"), "limit": d.get("limit"), "pressure": p}
