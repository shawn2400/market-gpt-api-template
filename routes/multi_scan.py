# routes/multi_scan.py
from __future__ import annotations
import os
from typing import Any, Dict, List
import requests
import pandas as pd
from fastapi import APIRouter, Query

from utils.indicators_ext import add_extended_indicators, extended_score_last_row
from utils.top_volume import get_top_volume_symbols

FUTURES_BASE = os.getenv("BINANCE_FUTURES_HTTP_BASE", "https://fapi.binance.com")

router = APIRouter(tags=["Scan"])

def _fetch_klines(symbol: str, interval: str = "15m", limit: int = 200) -> pd.DataFrame:
    url = f"{FUTURES_BASE}/fapi/v1/klines"
    r = requests.get(url, params={"symbol": symbol, "interval": interval, "limit": int(limit)}, timeout=10)
    r.raise_for_status()
    data = r.json()
    if not data:
        return pd.DataFrame()
    cols = ["open_time","open","high","low","close","volume","close_time",
            "qv","nTrades","taker_base","taker_quote","x"]
    df = pd.DataFrame(data, columns=cols[:len(data[0])])
    for c in ("open","high","low","close","volume"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df[["open","high","low","close","volume"]]

@router.get("/scan/top-volume", summary="Scan top-volume symbols concurrently (extended)", operation_id="getScanTopVolume")
def get_scan_top_volume(
    market: str = Query("futures", enum=["futures","spot"]),
    quote: str = Query("USDT"),
    limit: int = Query(50, ge=1, le=200),
    timeframe: str = Query("15m"),
    bars: int = Query(200, ge=50, le=1500),
    trending_only: bool = Query(False, description="אם true – רק טרנד פעיל"),
    min_adx: float = Query(20.0, ge=5.0, le=60.0),
    ema_fast: int = Query(21, ge=3, le=200),
    ema_slow: int = Query(50, ge=5, le=400),
    adx_len: int = Query(14, ge=5, le=50),
    st_period: int = Query(10, ge=5, le=50),
    st_factor: float = Query(3.0, ge=1.0, le=10.0),
    ich_conv: int = Query(9, ge=5, le=50),
    ich_base: int = Query(26, ge=10, le=100),
    ich_span_b: int = Query(52, ge=20, le=200),
    ms_lookback: int = Query(5, ge=2, le=20),
    ms_pivot_span: int = Query(3, ge=1, le=10),
    concurrency: int = Query(16, ge=2, le=64),  # כרגע סריקה סדרתית
) -> Dict[str, Any]:
    ok, symbols = get_top_volume_symbols(market=market, quote=quote, limit=limit)
    if not ok or not symbols:
        return {"ok": False, "count": 0, "signals": [], "note": "no symbols or provider error"}

    signals: List[Dict[str, Any]] = []
    for sym in symbols:
        try:
            df = _fetch_klines(sym, timeframe, bars)
            if df.empty:
                continue
            d2 = add_extended_indicators(
                df,
                ema_fast=ema_fast, ema_slow=ema_slow, adx_len=adx_len,
                st_period=st_period, st_factor=st_factor,
                ichimoku_conv=ich_conv, ichimoku_base=ich_base, ichimoku_span_b=ich_span_b,
                ms_lookback=ms_lookback, ms_pivot_span=ms_pivot_span,
            )
            if d2.empty:
                continue
            row = d2.iloc[-1]
            score, side, conf, reason = extended_score_last_row(row)

            if trending_only:
                if not bool(row.get("trending", False)):
                    continue
                if float(row.get("adx", 0.0)) < float(min_adx):
                    continue

            signals.append({
                "symbol": sym,
                "timeframe": timeframe,
                "side": side,
                "score": score,
                "note": reason,
                "details": {
                    "close": float(row.get("close", float("nan"))),
                    "ema_fast": float(row.get("ema_fast", float("nan"))),
                    "ema_slow": float(row.get("ema_slow", float("nan"))),
                    "adx": float(row.get("adx", float("nan"))),
                    "stoch_k": float(row.get("stoch_k", float("nan"))),
                    "stoch_d": float(row.get("stoch_d", float("nan"))),
                    "ich_state": str(row.get("ichimoku_state")),
                    "ms_trend": str(row.get("ms_trend")),
                    "supertrend": float(row.get("supertrend", float("nan"))),
                    "trend_dir": str(row.get("trend_dir")),
                    "trending": bool(row.get("trending", False)),
                    "confidence": conf,
                },
            })
        except Exception:
            continue

    signals.sort(key=lambda s: s.get("score", 0.0), reverse=True)
    return {"ok": True, "count": len(signals), "signals": signals}
















































