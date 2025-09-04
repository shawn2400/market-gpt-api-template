# utils/get_klines.py
from __future__ import annotations
import asyncio, time
from typing import Optional, List, Dict, Any
import httpx, pandas as pd
from utils.symbols import normalize_symbol

BINANCE_FAPI = "https://fapi.binance.com"
BINANCE_SPOT = "https://api.binance.com"

_INVALID_TTL = 900
_invalid_cache: Dict[str, float] = {}

_INTERVAL_SEC = {
    "1m": 60, "3m": 180, "5m": 300, "15m": 900, "30m": 1800,
    "1h": 3600, "2h": 7200, "4h": 14400, "1d": 86400
}


def _cache_key(market: str, symbol: str) -> str:
    return f"{market}:{symbol.upper()}"


def _is_invalid(market: str, symbol: str) -> bool:
    return _invalid_cache.get(_cache_key(market, symbol), 0.0) > time.time()


def _mark_invalid(market: str, symbol: str) -> None:
    _invalid_cache[_cache_key(market, symbol)] = time.time() + _INVALID_TTL


def _endpoint_for(market_type: str) -> str:
    return f"{BINANCE_SPOT}/api/v3/klines" if str(market_type).lower() == "spot" else f"{BINANCE_FAPI}/fapi/v1/klines"


def _to_dataframe(kl: List[List[Any]]) -> pd.DataFrame:
    cols = [
        "open_time","open","high","low","close","volume",
        "close_time","quote_asset_volume","number_of_trades",
        "taker_buy_base","taker_buy_quote","ignore"
    ]
    df = pd.DataFrame(kl, columns=cols)
    for c in ["open","high","low","close","volume","quote_asset_volume","taker_buy_base","taker_buy_quote"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["open_time"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
    df["close_time"] = pd.to_datetime(df["close_time"], unit="ms", utc=True)
    df = df.set_index("open_time", drop=False)
    df["timestamp"] = df["close_time"]
    return df


async def _rest_klines_async(symbol: str, interval: str, limit: int, market_type: str) -> pd.DataFrame:
    market = "spot" if str(market_type).lower() == "spot" else "futures"
    sym_in = (symbol or "").upper().strip()
    if not sym_in:
        raise ValueError("symbol is required")
    if _is_invalid(market, sym_in):
        return pd.DataFrame()
    try:
        norm = normalize_symbol(sym_in) if market == "futures" else sym_in
    except Exception:
        _mark_invalid(market, sym_in)
        raise
    url = _endpoint_for(market_type)
    params = {"symbol": norm, "interval": interval, "limit": int(limit)}
    async with httpx.AsyncClient(timeout=8.0) as x:
        r = await x.get(url, params=params)
        r.raise_for_status()
        data = r.json()
        if not isinstance(data, list) or len(data) == 0:
            return pd.DataFrame()
    return _to_dataframe(data)


def _resample_ohlcv(df_small: pd.DataFrame, target_interval: str) -> pd.DataFrame:
    if df_small is None or df_small.empty:
        return pd.DataFrame()
    rule = {"1h": "1H","2h": "2H","4h": "4H","1d": "1D"}.get(target_interval.lower())
    if not rule:
        return df_small
    if not isinstance(df_small.index, pd.DatetimeIndex):
        df_small = df_small.set_index("open_time")
    agg = df_small.resample(rule, origin="start").agg({
        "open":"first","high":"max","low":"min","close":"last","volume":"sum"
    }).dropna()
    agg["open_time"] = agg.index
    agg["close_time"] = agg.index + (
        pd.to_timedelta(_INTERVAL_SEC[target_interval.lower()], unit="s") - pd.to_timedelta(1,"ms")
    )
    agg["timestamp"] = agg["close_time"]
    return agg


async def get_klines(symbol: str, interval: str, limit: int = 150, market_type: str = "futures") -> pd.DataFrame:
    interval = (interval or "15m").lower()
    try:
        df = await _rest_klines_async(symbol, interval, limit, market_type)
        if not df.empty:
            return df
    except Exception:
        pass
    if interval in ("1h","2h","4h","1d"):
        for base in ("5m","1m"):
            try:
                factor = max(1, int(_INTERVAL_SEC[interval] // _INTERVAL_SEC[base]))
                need = min(1500, limit * factor + 5)
                small = await _rest_klines_async(symbol, base, need, market_type)
                if small.empty:
                    continue
                agg = _resample_ohlcv(small, interval)
                if not agg.empty:
                    return agg.tail(limit)
            except Exception:
                continue
    return pd.DataFrame()


def get_klines_sync(symbol: str, interval: str, limit: int = 150, market_type: str = "futures") -> pd.DataFrame:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop and loop.is_running():
        return pd.DataFrame()
    return asyncio.run(get_klines(symbol, interval, limit, market_type))


async def aget_klines(symbol: str, interval: str, limit: int = 150, market_type: str = "futures") -> pd.DataFrame:
    return await get_klines(symbol, interval, limit, market_type)













































