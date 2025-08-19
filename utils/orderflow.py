# utils/orderflow.py
from __future__ import annotations
import os
from typing import Dict, Any, List
import httpx
import math

_FAPI = os.getenv("BINANCE_FUTURES_HTTP_BASE", "https://fapi.binance.com").rstrip("/")

def _safe_float(x) -> float:
    try:
        return float(x)
    except Exception:
        return math.nan

def _cvd_from_aggtrades(trades: List[dict], window: int) -> Dict[str, float]:
    """
    isBuyerMaker == True  -> sell (taker is buyer? binance semantics: True means the buyer is the market maker -> effectively SELL aggression)
    Practically: treat isBuyerMaker True as SELL volume, False as BUY volume.
    """
    buys, sells, cvd = 0.0, 0.0, 0.0
    for t in trades[-window:]:
        q = _safe_float(t.get("q"))
        if t.get("m"):  # isBuyerMaker
            sells += q
            cvd -= q
        else:
            buys += q
            cvd += q
    total = buys + sells if (buys + sells) > 0 else 1.0
    return {
        "cvd": cvd,
        "buy_vol": buys,
        "sell_vol": sells,
        "buy_share": buys / total,
        "sell_share": sells / total,
    }

def _imbalance_from_depth(bids: List[List[str]], asks: List[List[str]], levels: int = 50) -> Dict[str, float]:
    nb = min(levels, len(bids))
    na = min(levels, len(asks))
    bid_vol = sum(_safe_float(q) for _, q in bids[:nb])
    ask_vol = sum(_safe_float(q) for _, q in asks[:na])
    total = (bid_vol + ask_vol) if (bid_vol + ask_vol) > 0 else 1.0
    return {
        "bid_vol": bid_vol,
        "ask_vol": ask_vol,
        "imbalance": (bid_vol - ask_vol) / total
    }

def get_orderflow_snapshot(symbol: str, trades_limit: int = 800, depth_limit: int = 500, cvd_window: int = 300) -> Dict[str, Any]:
    symbol = symbol.upper().strip()

    with httpx.Client(timeout=6.0) as client:
        # aggTrades
        r1 = client.get(f"{_FAPI}/fapi/v1/aggTrades", params={"symbol": symbol, "limit": min(trades_limit, 1000)})
        r1.raise_for_status()
        trades = r1.json()

        # depth
        # valid limits: 5, 10, 20, 50, 100, 500, 1000
        depth_limit = max(5, min(depth_limit, 1000))
        if depth_limit not in (5, 10, 20, 50, 100, 500, 1000):
            # round to nearest valid
            for opt in (5, 10, 20, 50, 100, 500, 1000):
                if depth_limit <= opt:
                    depth_limit = opt
                    break
        r2 = client.get(f"{_FAPI}/fapi/v1/depth", params={"symbol": symbol, "limit": depth_limit})
        r2.raise_for_status()
        depth = r2.json()

    cvd = _cvd_from_aggtrades(trades, window=min(cvd_window, len(trades)))
    bids = depth.get("bids", [])
    asks = depth.get("asks", [])
    imb = _imbalance_from_depth(bids, asks, levels=min(50, depth_limit))

    best_bid = _safe_float(bids[0][0]) if bids else None
    best_ask = _safe_float(asks[0][0]) if asks else None
    mid = None
    if best_bid is not None and best_ask is not None:
        mid = (best_bid + best_ask) / 2.0

    return {
        "ok": True,
        "symbol": symbol,
        "limits": {"trades": trades_limit, "depth": depth_limit, "cvd_window": cvd_window},
        "cvd": cvd,
        "depth": {
            "best_bid": best_bid,
            "best_ask": best_ask,
            "mid": mid,
            "imbalance": imb,
        }
    }





