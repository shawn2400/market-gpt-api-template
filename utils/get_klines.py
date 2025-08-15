# utils/get_klines.py
from __future__ import annotations
import os
import time
from typing import Optional, List, Dict, Any, Tuple

import httpx
import pandas as pd

from utils.symbols import normalize_symbol, SymbolsCache

BINANCE_FAPI = "https://fapi.binance.com"
BINANCE_SPOT = "https://api.binance.com"

_symbols_cache_fut = SymbolsCache(market="futures")
_symbols_cache_spot = SymbolsCache(market="spot")

# --- Invalid-cache settings ---
# קיצור TTL ל-120ש׳ + החרגה מלאה ל-BTCUSDT (לא מסמנים/לא בודקים invalid)
_INVALID_TTL = int(os.getenv("KLINES_INVALID_TTL", "120"))  # seconds
_ALWAYS_ALLOWED = {"BTCUSDT"}  # symbols שאף פעם לא ייחסמו (anchor)

_invalid_cache: Dict[Tuple[str, str], float] = {}  # {(market, symbol_upper): ts_expire}

def _is_always_allowed(symbol: str) -> bool:
    return symbol.upper() in _ALWAYS_ALLOWED

def _is_invalid(market: str, symbol: str) -> bool:
    if _is_always_allowed(symbol):
        return False
    return _invalid_cache.get((market, symbol.upper()), 0.0) > time.time()

def _mark_invalid(market: str, symbol: str) -> None:
    if _is_always_allowed(symbol):
        # לעולם לא מסמנים BTCUSDT כ-invalid
        return
    _invalid_cache[(market, symbol.upper())] = time.time() + _INVALID_TTL

def _endpoint_for(market_type: str) -> str:
    if str(market_type).lower() == "spot":
        return f"{BINANCE_SPOT}/api/v3/klines"
    return f"{BINANCE_FAPI}/fapi/v1/klines"

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
    market = "spot" if str(market_type).lower() == "spot" else "futures"
    sym_in = symbol.upper()

    # אל תחסום סמלים מוחרגים (כמו BTCUSDT) – גם אם סומנו בעבר
    if _is_invalid(market, sym_in):
        raise ValueError(f"Symbol {sym_in} recently marked invalid for {market}")

    try:
        norm = normalize_symbol(
            sym_in,
            market=market,
            cache=_symbols_cache_spot if market == "spot" else _symbols_cache_fut,
        )
    except Exception:
        _mark_invalid(market, sym_in)
        raise

    url = _endpoint_for(market)
    params = {"symbol": norm, "interval": interval, "limit": int(limit)}

    async with httpx.AsyncClient(timeout=5.0) as x:
        r = await x.get(url, params=params)
        try:
            r.raise_for_status()
        except httpx.HTTPStatusError:
            # על שגיאות 4xx מסמנים invalid — אבל לא לסמלים מוחרגים (BTCUSDT)
            if 400 <= r.status_code < 500:
                _mark_invalid(market, sym_in)
            raise

        data = r.json()
        if not isinstance(data, list) or len(data) == 0:
            return None

    df = _to_dataframe(data)
    if len(df) < 10:
        return None
    return df



































