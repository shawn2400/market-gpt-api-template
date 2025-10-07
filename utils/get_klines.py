# utils/get_klines.py
from __future__ import annotations
import asyncio
from typing import List, Dict, Any
import httpx
import pandas as pd
from utils.symbols import normalize_symbol

BINANCE_FAPI = "https://fapi.binance.com"
BINANCE_SPOT = "https://api.binance.com"

_last_ts: Dict[str, int] = {}

def _cache_key(market: str, symbol: str, interval: str) -> str:
    return f"{market}:{symbol}:{interval}"

def _endpoint_for(market_type: str) -> str:
    return f"{BINANCE_SPOT}/api/v3/klines" if market_type == "spot" else f"{BINANCE_FAPI}/fapi/v1/klines"

def _to_dataframe(kl: List[List[Any]]) -> pd.DataFrame:
    cols = ["open_time","open","high","low","close","volume",
            "close_time","qav","n_trades","taker_base","taker_quote","ignore"]
    df = pd.DataFrame(kl, columns=cols)
    if df.empty:
        return df
    for c in ["open","high","low","close","volume"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["open_time"]  = pd.to_datetime(df["open_time"], unit="ms", utc=True)
    df["close_time"] = pd.to_datetime(df["close_time"], unit="ms", utc=True)
    df = df.set_index("open_time", drop=False)
    df["timestamp"] = df["close_time"]
    return df

async def _rest_klines(symbol: str, interval: str, limit: int, market_type: str) -> pd.DataFrame:
    norm = normalize_symbol(symbol) if market_type == "futures" else symbol
    params = {"symbol": norm, "interval": interval, "limit": int(limit)}
    async with httpx.AsyncClient(timeout=8.0) as x:
        r = await x.get(_endpoint_for(market_type), params=params)
        r.raise_for_status()
        return _to_dataframe(r.json())

async def get_klines(symbol: str, interval: str, limit: int = 150, market_type: str = "futures") -> pd.DataFrame:
    key = _cache_key(market_type, symbol, interval)
    since = _last_ts.get(key, 0)

    async def _fetch(mtype: str, use_since: bool) -> pd.DataFrame:
        try:
            params = {"symbol": normalize_symbol(symbol) if mtype == "futures" else symbol,
                      "interval": interval, "limit": int(limit)}
            if use_since and since:
                params["startTime"] = since + 1
            async with httpx.AsyncClient(timeout=8.0) as x:
                r = await x.get(_endpoint_for(mtype), params=params)
                r.raise_for_status()
                df = _to_dataframe(r.json())
                if not df.empty:
                    _last_ts[key] = int(df["close_time"].iloc[-1].timestamp() * 1000)
                return df
        except Exception:
            return pd.DataFrame()

    # 1) Futures עם since (אינקרמנטלי), אם אין – פולפאץ'
    df = await _fetch("futures", use_since=True)
    if df.empty:
        df = await _fetch("futures", use_since=False)
    # 2) פולבאק ל־Spot
    if df.empty:
        df = await _fetch("spot", use_since=False)
    return df

def get_klines_sync(symbol: str, interval: str, limit: int = 150, market_type: str = "futures") -> pd.DataFrame:
    try:
        loop = asyncio.get_running_loop()
        if loop.is_running():
            fut = asyncio.run_coroutine_threadsafe(get_klines(symbol, interval, limit, market_type), loop)
            return fut.result(timeout=10)
    except RuntimeError:
        return asyncio.run(get_klines(symbol, interval, limit, market_type))
    except Exception:
        return pd.DataFrame()


















































