# utils/orderflow.py
from __future__ import annotations
import os
import math
from typing import Dict, Any, List, Tuple
from datetime import datetime, timezone

from binance import Client

_BKEY = os.getenv("BINANCE_API_KEY") or ""
_BSEC = os.getenv("BINANCE_API_SECRET") or ""

def _get_client() -> Client:
    # Spot client מספיק ל-aggTrades/order_book גם בסביבת futures-public
    # אם ברצונך להשתמש ב-Futures HTTP מפורש – אפשר להגדיר Client.futures_...
    return Client(api_key=_BKEY, api_secret=_BSEC)

def _cvd_from_trades(trades: List[dict], window: int) -> Tuple[float, float, float]:
    """
    מחושב CVD פשוט: סכום (qty * side), כאשר side נגזר price לעומת agg.
    כאן משתמשים ב-isBuyerMaker: כאשר True → מכירה פאסיבית, לכן נחשב כ-flow של מוכרים.
    """
    cvd = 0.0
    buys = 0.0
    sells = 0.0
    for t in trades[-window:]:
        qty = float(t.get("q") or t.get("quantity") or 0.0)
        is_bm = bool(t.get("m") or t.get("isBuyerMaker"))
        if is_bm:
            # קונה היה maker? ב-aggTrades m=True -> הקונה הוא maker (בדרך כלל "sell pressure")
            sells += qty
            cvd -= qty
        else:
            buys += qty
            cvd += qty
    return cvd, buys, sells

def _depth_imbalance(depth: dict, levels: int) -> Dict[str, Any]:
    bids = depth.get("bids", [])[:levels]
    asks = depth.get("asks", [])[:levels]
    bid_vol = sum(float(b[1]) for b in bids)
    ask_vol = sum(float(a[1]) for a in asks)
    total = bid_vol + ask_vol
    imb = ((bid_vol - ask_vol) / total) * 100.0 if total > 0 else 0.0
    best_bid = float(bids[0][0]) if bids else None
    best_ask = float(asks[0][0]) if asks else None
    spread = (best_ask - best_bid) if (best_ask and best_bid) else None
    return {
        "bid_vol": bid_vol,
        "ask_vol": ask_vol,
        "imbalance_pct": imb,
        "best_bid": best_bid,
        "best_ask": best_ask,
        "spread": spread,
    }

def _iceberg_heuristics(trades: List[dict], depth: dict) -> Dict[str, Any]:
    """
    היוריסטיקה פשוטה – מזהה רצפים קצרים של עסקאות בגודל דומה.
    """
    tag = None
    cluster = 0
    last_qty = None
    for t in trades[-50:]:
        qty = float(t.get("q") or t.get("quantity") or 0.0)
        if last_qty is not None and abs(qty - last_qty) / (last_qty + 1e-9) < 0.05:
            cluster += 1
        else:
            cluster = 1
        last_qty = qty
    if cluster >= 5:
        tag = "possible-iceberg"
    return {"iceberg_hint": tag, "cluster_len": cluster}

def get_orderflow_snapshot(symbol: str, trades_limit: int = 800, depth_limit: int = 500, cvd_window: int = 300) -> Dict[str, Any]:
    client = _get_client()
    # aggTrades (spot) – עבור futures אפשר גם להשתמש ב-futures aggTrades public אם תרצה
    trades = client.get_aggregate_trades(symbol=symbol, limit=min(trades_limit, 1000))
    depth = client.get_order_book(symbol=symbol, limit=max(5, min(depth_limit, 1000)))

    cvd, buys, sells = _cvd_from_trades(trades, window=min(cvd_window, len(trades)))
    depth_stats = _depth_imbalance(depth, levels=min(100, len(depth.get("bids", []))))

    ice = _iceberg_heuristics(trades, depth)

    now = datetime.now(timezone.utc).isoformat()
    return {
        "ts": now,
        "cvd": cvd,
        "buys": buys,
        "sells": sells,
        "depth": depth_stats,
        "icebergs": ice,
        "trades_sample": len(trades),
        "depth_levels": {
            "bids": len(depth.get("bids", [])),
            "asks": len(depth.get("asks", [])),
        },
    }


