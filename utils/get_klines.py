# utils/get_klines.py
from __future__ import annotations
import os
import time
from typing import Optional, List, Dict, Any, Tuple

import httpx
import pandas as pd

from utils.symbols import normalize_symbol, SymbolsCache

BINANCE_FAPI = os.getenv("BINANCE_FUTURES_HTTP_BASE", "https://fapi.binance.com").rstrip("/")
BINANCE_SPOT = os.getenv("BINANCE_SPOT_HTTP_BASE", "https://api.binance.com").rstrip("/")

_symbols_cache_fut = SymbolsCache(market="futures")
_symbols_cache_spot = SymbolsCache(market="spot")

_INVALID_TTL = 3600  # seconds
_invalid_cache: Dict[Tuple[str, str], float] = {}  # {(market, norm_symbol): expire_ts}


def _is_invalid(market: str, norm_symbol: str) -> bool:
    return _invalid_cache.get((market, norm_symbol.upper()), 0.0) > time.time()


def _mark_invalid(market: str, norm_symbol: str) -> None:
    _invalid_cache[(market, norm_symbol.upper())] = time.time() + _INVALID_TTL


def _endpoint_for(market_type: str) -> str:
    return f"{BINANCE_SPOT}/api/v3/klines" if str(market_type).lower() == "spot" else f"{BINANCE_FAPI}/fapi/v1/klines"


def _to_dataframe(kl: List[List[Any]]) -> pd.DataFrame:
    cols = [
        "open_time", "open", "high", "low", "close", "volume",
        "close_time", "quote_asset_volume", "number_of_trades",
        "taker_buy_base", "taker_buy_quote", "ignore",
    ]
    df = pd.DataFrame(kl, columns=cols)
    num_cols = ["open", "high", "low", "close", "volume", "quote_asset_volume", "taker_buy_base", "taker_buy_quote"]
    for c in num_cols:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["open_time"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
    df["close_time"] = pd.to_datetime(df["close_time"], unit="ms", utc=True)
    df["timestamp"] = df["close_time"]
    return df


async def get_klines(
    symbol: str,
    interval: str,
    limit: int = 150,
    market_type: str = "futures",
) -> Optional[pd.DataFrame]:
    """
    Fetch klines from Binance with robust symbol normalization and a 1h blacklist for bad symbols.
    Order: normalize -> blacklist check -> request.
    """
    market = "spot" if str(market_type).lower() == "spot" else "futures"

    # 1) normalize first (this also resolves SHIBUSDT -> 1000SHIBUSDT in futures)
    try:
        norm = normalize_symbol(symbol, market=market, cache=_symbols_cache_spot if market == "spot" else _symbols_cache_fut)
    except Exception:
        # don't blacklist raw symbol; we only blacklist normalized names
        raise

    # 2) now check blacklist for the normalized symbol
    if _is_invalid(market, norm):
        raise ValueError(f"Symbol {norm} recently marked invalid for {market}")

    # 3) fetch
    url = _endpoint_for(market)
    params = {"symbol": norm, "interval": interval, "limit": int(limit)}

    async with httpx.AsyncClient(timeout=5.0) as x:
        r = await x.get(url, params=params)
        try:
            r.raise_for_status()
        except httpx.HTTPStatusError:
            # blacklist only normalized symbol
            if 400 <= r.status_code < 500:
                _mark_invalid(market, norm)
            raise

        data = r.json()
        if not isinstance(data, list) or len(data) == 0:
            return None

    df = _to_dataframe(data)
    if len(df) < 10:
        return None
    return df

































