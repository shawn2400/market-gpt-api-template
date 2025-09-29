# core/scheduler.py
from __future__ import annotations
import time, asyncio, threading
import pandas as pd
from utils.get_klines import get_klines_sync
from core.signal_fuser import fuse_signals, enrich_with_funding

def _fetch_feeds(symbol: str, tf: str) -> dict:
    """
    כאן חבר את המקורות שלך:
      • delta_per_bar  – אגרגציית aggTrades -> Δ לכל נר
      • oi_df          – DataFrame עם עמודה 'oi'
      • df_spot        – DataFrame עם עמודה 'price'
      • df_mark        – DataFrame עם עמודה 'markPrice'
      • best_bid/ask   – מחיר ספר עדכני
      • mark/index     – sanity check
    """
    feeds = {"symbol": symbol}
    # TODO: חבר פונקציות אמת שלך
    feeds["delta_per_bar"] = None
    feeds["oi_df"] = None
    feeds["df_spot"] = None
    feeds["df_mark"] = None
    feeds["best_bid"] = None; feeds["best_ask"] = None
    feeds["mark"] = None; feeds["index"] = None
    return feeds

def scan_once(symbol: str, tf: str = "15m"):
    df = get_klines_sync(symbol, tf, 600, "futures")
    feeds = _fetch_feeds(symbol, tf)
    out = fuse_signals(df, symbol=symbol, tf=tf, feeds=feeds)
    if out.get("ok"):
        # obfuscate: בצע את הטרייד שלך כאן
        # העשרה ב-funding (async) – אופציונלי
        try:
            loop = asyncio.get_event_loop()
            out = loop.run_until_complete(enrich_with_funding(out, symbol=symbol, side=out["side"]))
        except Exception:
            pass
    return out

