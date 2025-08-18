# utils/orderflow.py
from __future__ import annotations
import os
import time
from typing import Dict, Any, Tuple, List

import requests
import numpy as np
import pandas as pd

__all__ = [
    "get_agg_trades_df",
    "get_depth_snapshot",
    "compute_cvd",
    "detect_iceberg_presence",
    "get_orderflow_snapshot",
]

FUTURES_BASE = os.getenv("BINANCE_FUTURES_HTTP_BASE", "https://fapi.binance.com")
HTTP_TIMEOUT = float(os.getenv("ORDERFLOW_TIMEOUT_SEC", "8"))
CACHE_TTL_TRADES = float(os.getenv("ORDERFLOW_TRADES_TTL_SEC", "2.5"))
CACHE_TTL_DEPTH  = float(os.getenv("ORDERFLOW_DEPTH_TTL_SEC", "2.0"))

_s = requests.Session()
_s.trust_env = False
_s.headers.update({
    "User-Agent": "AlgoGPT/2 orderflow",
    "Accept": "application/json",
})

_cache_trades: Dict[str, Dict[str, Any]] = {}
_cache_depth: Dict[str, Dict[str, Any]] = {}


def _get(url: str, params: Dict[str, Any] | None = None, timeout: float = HTTP_TIMEOUT):
    r = _s.get(url, params=params or {}, timeout=timeout)
    r.raise_for_status()
    return r.json()


def get_agg_trades_df(symbol: str, limit: int = 1000) -> pd.DataFrame:
    """
    מושך AggTrades מ-Binance Futures (עד 1000 אחרונים) ומחזיר DataFrame:
      columns: time, price, qty, is_buyer_maker
    """
    limit = max(1, min(int(limit), 1000))
    now = time.monotonic()
    ck = f"{symbol}:{limit}"

    ent = _cache_trades.get(ck)
    if ent and (now - ent["t"] <= CACHE_TTL_TRADES):
        return ent["df"].copy()

    data = _get(f"{FUTURES_BASE}/fapi/v1/aggTrades", params={"symbol": symbol, "limit": limit})

    if not data:
        df = pd.DataFrame(columns=["time", "price", "qty", "is_buyer_maker"])
    else:
        # futures aggTrades fields: a(pId), p, q, f, l, T, m, M
        df = pd.DataFrame([{
            "time": int(x.get("T", 0)),
            "price": float(x.get("p", 0.0)),
            "qty": float(x.get("q", 0.0)),
            "is_buyer_maker": bool(x.get("m", False)),  # True => seller-initiated
        } for x in data], columns=["time", "price", "qty", "is_buyer_maker"])

    _cache_trades[ck] = {"t": now, "df": df}
    return df.copy()


def get_depth_snapshot(symbol: str, limit: int = 500) -> Dict[str, Any]:
    """
    דאפית׳ (BBO snapshot) עם עד 1000 רמות. מחזיר:
      bids: List[[price, qty]], asks: List[[price, qty]]
      bid_volume, ask_volume, imbalance, mid, best_bid, best_ask
    """
    limit = int(limit)
    if limit not in (5, 10, 20, 50, 100, 500, 1000):
        limit = 500

    now = time.monotonic()
    ck = f"{symbol}:{limit}"
    ent = _cache_depth.get(ck)
    if ent and (now - ent["t"] <= CACHE_TTL_DEPTH):
        return dict(ent["data"])

    j = _get(f"{FUTURES_BASE}/fapi/v1/depth", params={"symbol": symbol, "limit": limit})

    bids = [[float(p), float(q)] for p, q in (j.get("bids") or [])]
    asks = [[float(p), float(q)] for p, q in (j.get("asks") or [])]

    bid_vol = float(sum(q for _, q in bids))
    ask_vol = float(sum(q for _, q in asks))

    best_bid = bids[0][0] if bids else np.nan
    best_ask = asks[0][0] if asks else np.nan
    mid = float((best_bid + best_ask) / 2.0) if np.isfinite(best_bid) and np.isfinite(best_ask) else np.nan

    imb = 0.0
    if (bid_vol + ask_vol) > 0:
        imb = float((bid_vol - ask_vol) / (bid_vol + ask_vol))

    out = {
        "bids": bids,
        "asks": asks,
        "bid_volume": bid_vol,
        "ask_volume": ask_vol,
        "imbalance": imb,       # -1..+1 (חיובי = לחץ קנייה)
        "mid": mid,
        "best_bid": best_bid,
        "best_ask": best_ask,
        "levels": limit,
    }
    _cache_depth[ck] = {"t": now, "data": out}
    return dict(out)


def compute_cvd(df_trades: pd.DataFrame, window_trades: int = 300) -> Dict[str, Any]:
    """
    CVD ע״פ aggTrades:
      delta = +qty אם BUY-initiated (m=False), -qty אם SELL-initiated (m=True).
    מחזיר:
      cvd_series (רק אם ביקשת), cvd_last, cvd_change_n, buy_ratio, sell_ratio, mean_qty
    """
    if df_trades.empty:
        return {"cvd_last": 0.0, "cvd_change_n": 0.0, "buy_ratio": 0.0, "sell_ratio": 0.0, "mean_qty": 0.0}

    d = df_trades.tail(int(max(1, window_trades))).copy()
    d["delta"] = np.where(d["is_buyer_maker"], -d["qty"], d["qty"])
    d["cvd"] = d["delta"].cumsum()

    buys = float((~d["is_buyer_maker"]).sum())
    sells = float((d["is_buyer_maker"]).sum())
    total = max(1.0, buys + sells)
    buy_ratio = float(buys / total)
    sell_ratio = float(sells / total)

    cvd_last = float(d["cvd"].iloc[-1])
    cvd_change = float(d["cvd"].iloc[-1] - d["cvd"].iloc[0]) if len(d) > 1 else float(d["cvd"].iloc[-1])
    mean_qty = float(d["qty"].mean()) if len(d) else 0.0

    return {
        "cvd_last": cvd_last,
        "cvd_change_n": cvd_change,
        "buy_ratio": buy_ratio,
        "sell_ratio": sell_ratio,
        "mean_qty": mean_qty,
    }


def detect_iceberg_presence(df_trades: pd.DataFrame) -> Dict[str, Any]:
    """
    היוריסטיקה פשוטה ל״Iceberg orders״:
      - הרבה עסקאות קטנות (מתחת ל-25% מהחציון) באותו מחיר/טווח קטן, בזמן קצר.
      - בוחן חלון אחרון של ~400 עסקאות.
    מחזיר: present (bool), score (0..1), clusters (int)
    """
    if df_trades.empty:
        return {"present": False, "score": 0.0, "clusters": 0}

    d = df_trades.tail(400).copy()
    if len(d) < 40:
        return {"present": False, "score": 0.0, "clusters": 0}

    price_eps = max(0.5, np.nanmedian(d["price"]) * 0.00005)  # 5bps או 0.5$
    q_med = np.nanmedian(d["qty"])
    small_thr = max(1e-9, q_med * 0.25)

    # קיבוץ בקירוב לפי price bucket
    buckets = np.floor(d["price"] / price_eps)
    d["bucket"] = buckets

    # נספור בכל bucket כמה עסקאות קטנות ב-60 השניות האחרונות של החלון
    t_min = d["time"].max() - 60_000
    d_recent = d[d["time"] >= t_min]

    clusters = 0
    cluster_scores: List[float] = []
    for b, grp in d_recent.groupby("bucket"):
        small_cnt = int((grp["qty"] <= small_thr).sum())
        total_cnt = int(len(grp))
        if total_cnt >= 8 and small_cnt >= 4:
            clusters += 1
            cluster_scores.append(min(1.0, (small_cnt / max(1.0, total_cnt)) * 1.5))

    score = float(min(1.0, sum(cluster_scores))) if cluster_scores else 0.0
    present = bool(score >= 0.6 or clusters >= 2)

    return {"present": present, "score": score, "clusters": int(clusters)}


def get_orderflow_snapshot(
    symbol: str,
    *,
    trades_limit: int = 800,
    depth_limit: int = 500,
    cvd_window: int = 300,
) -> Dict[str, Any]:
    """
    תצלום Order Flow מיידי:
      - CVD + יחסי קניה/מכירה
      - דאפית׳: אימבלאנס, bid/ask volumes, best bid/ask
      - איתות Icebergs (היוריסטי)
    """
    try:
        trades = get_agg_trades_df(symbol, limit=trades_limit)
        depth = get_depth_snapshot(symbol, limit=depth_limit)
        cvd = compute_cvd(trades, window_trades=cvd_window)
        ice = detect_iceberg_presence(trades)

        return {
            "ok": True,
            "symbol": symbol,
            "cvd": cvd,
            "depth": depth,
            "icebergs": ice,
            "ts": int(time.time()),
        }
    except Exception as e:
        return {"ok": False, "symbol": symbol, "error": str(e), "ts": int(time.time())}

