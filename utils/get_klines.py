from __future__ import annotations
import asyncio, random, os
from typing import List, Dict, Any
import pandas as pd

from utils.symbols import normalize_symbol
from utils.http_client import safe_get

BINANCE_FAPI = os.getenv("BINANCE_FUTURES_HTTP_BASE", "https://fapi.binance.com").rstrip("/")
BINANCE_SPOT = os.getenv("BINANCE_SPOT_HTTP_BASE", "https://api.binance.com").rstrip("/")

_BASE_PAUSE_MS = int(os.getenv("KLINES_BASE_PAUSE_MS", "60"))
_JITTER_MS_MIN = int(os.getenv("KLINES_JITTER_MS_MIN", "20"))
_JITTER_MS_MAX = int(os.getenv("KLINES_JITTER_MS_MAX", "120"))

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

async def _sleep_jitter():
    ms = _BASE_PAUSE_MS + random.randint(_JITTER_MS_MIN, _JITTER_MS_MAX)
    await asyncio.sleep(ms / 1000.0)

async def _rest_klines(symbol: str, interval: str, limit: int, market_type: str, start_time: int | None) -> pd.DataFrame:
    norm_sym = normalize_symbol(symbol) if market_type == "futures" else symbol
    params: Dict[str, Any] = {"symbol": norm_sym, "interval": interval, "limit": int(limit)}
    if start_time:
        params["startTime"] = int(start_time)
    await _sleep_jitter()
    r = await safe_get(_endpoint_for(market_type), params=params, retries=3, retry_base=0.5)
    r.raise_for_status()
    return _to_dataframe(r.json())

async def get_klines(symbol: str, interval: str, limit: int = 150, market_type: str = "futures") -> pd.DataFrame:
    norm_key_sym = normalize_symbol(symbol) if market_type == "futures" else symbol
    key = _cache_key(market_type, norm_key_sym, interval)
    since = _last_ts.get(key, 0)

    df = pd.DataFrame()
    try:
        df = await _rest_klines(symbol, interval, limit, "futures", since + 1 if since else None)
    except Exception:
        df = pd.DataFrame()
    if df.empty:
        try:
            df = await _rest_klines(symbol, interval, limit, "futures", None)
        except Exception:
            df = pd.DataFrame()
    if df.empty:
        try:
            df = await _rest_klines(symbol, interval, limit, "spot", None)
        except Exception:
            df = pd.DataFrame()

    if not df.empty:
        _last_ts[key] = int(df["close_time"].iloc[-1].timestamp() * 1000)
    return df

def get_klines_sync(symbol: str, interval: str, limit: int = 150, market_type: str = "futures") -> pd.DataFrame:
    try:
        loop = asyncio.get_running_loop()
        if loop.is_running():
            fut = asyncio.run_coroutine_threadsafe(get_klines(symbol, interval, limit, market_type), loop)
            return fut.result(timeout=15)
    except RuntimeError:
        return asyncio.run(get_klines(symbol, interval, limit, market_type))
    except Exception:
        return pd.DataFrame()



















































