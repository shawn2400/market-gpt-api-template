# routes/scan.py
from __future__ import annotations

import os
from typing import Any, Dict, List
import requests
import pandas as pd
from fastapi import APIRouter, Body, Query

from utils.indicators_ext import add_extended_indicators, extended_score_last_row
from utils.top_volume import get_top_volume_symbols

FUTURES_BASE = os.getenv("BINANCE_FUTURES_HTTP_BASE", "https://fapi.binance.com")

router = APIRouter()


def _fetch_klines(symbol: str, interval: str = "15m", limit: int = 200) -> pd.DataFrame:
    url = f"{FUTURES_BASE}/fapi/v1/klines"
    r = requests.get(url, params={"symbol": symbol, "interval": interval, "limit": int(limit)}, timeout=10)
    r.raise_for_status()
    data = r.json()
    cols = ["open_time","open","high","low","close","volume","close_time",
            "quote_asset_volume","number_of_trades","taker_buy_base","taker_buy_quote","ignore"]
    df = pd.DataFrame(data, columns=cols[:len(data[0])]) if data else pd.DataFrame(columns=cols)
    for col in ("open","high","low","close","volume"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df[["open","high","low","close","volume"]].copy()


@router.get("/scan", operation_id="getScanInfo")
def get_scan_info() -> Dict[str, Any]:
    return {"ok": True, "count": 0, "signals": []}


@router.post("/scan", operation_id="postScanSingle")
def post_scan_single(
    payload: Dict[str, Any] = Body(..., example={"symbol": "BTCUSDT", "timeframe": "15m", "limit": 200})
) -> Dict[str, Any]:
    symbol = str(payload.get("symbol", "BTCUSDT"))
    timeframe = str(payload.get("timeframe", "15m"))
    limit = int(payload.get("limit", 200))
    df = _fetch_klines(symbol, timeframe, limit)
    d2 = add_extended_indicators(df)
    if len(d2) == 0:
        return {"ok": False, "count": 0, "signals": []}
    row = d2.iloc[-1]
    score, side, conf, reason = extended_score_last_row(row)
    sig = {
        "symbol": symbol,
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
    }
    return {"ok": True, "count": 1, "signals": [sig]}


@router.post("/scan/multi", operation_id="postScanMulti")
def post_scan_multi(
    payload: Dict[str, Any] = Body(..., example={"symbols": ["BTCUSDT","ETHUSDT"], "timeframe":"15m", "limit":200})
) -> Dict[str, Any]:
    symbols: List[str] = list(payload.get("symbols") or [])
    timeframe = str(payload.get("timeframe", "15m"))
    limit = int(payload.get("limit", 200))

    out: List[Dict[str, Any]] = []
    for sym in symbols:
        try:
            df = _fetch_klines(sym, timeframe, limit)
            d2 = add_extended_indicators(df)
            if len(d2) == 0:
                continue
            row = d2.iloc[-1]
            score, side, conf, reason = extended_score_last_row(row)
            out.append({
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
                    "ich_state": str(row.get("ichimoku_state")),
                    "ms_trend": str(row.get("ms_trend")),
                    "trending": bool(row.get("trending", False)),
                    "confidence": conf,
                },
            })
        except Exception:
            continue

    return {"ok": True, "count": len(out), "signals": out}


@router.get("/scan/top-volume", operation_id="getScanTopVolume")
def get_scan_top_volume(
    market: str = Query("futures", enum=["futures","spot"]),
    quote: str = Query("USDT"),
    limit: int = Query(50, ge=1, le=200),
    timeframe: str = Query("15m"),
    bars: int = Query(200, ge=50, le=1500),
    trending_only: bool = Query(False),
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
    if not ok:
        return {"ok": False, "count": 0, "signals": []}

    signals: List[Dict[str, Any]] = []
    for sym in symbols:
        try:
            df = _fetch_klines(sym, timeframe, bars)
            d2 = add_extended_indicators(
                df,
                ema_fast=ema_fast, ema_slow=ema_slow, adx_len=adx_len,
                st_period=st_period, st_factor=st_factor,
                ichimoku_conv=ich_conv, ichimoku_base=ich_base, ichimoku_span_b=ich_span_b,
                ms_lookback=ms_lookback, ms_pivot_span=ms_pivot_span,
            )
            if len(d2) == 0:
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
                    "ich_state": str(row.get("ichimoku_state")),
                    "ms_trend": str(row.get("ms_trend")),
                    "trending": bool(row.get("trending", False)),
                    "confidence": conf,
                },
            })
        except Exception:
            continue

    signals.sort(key=lambda s: s.get("score", 0.0), reverse=True)
    return {"ok": True, "count": len(signals), "signals": signals}





