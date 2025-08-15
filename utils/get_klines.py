# utils/get_klines.py
from __future__ import annotations
import time
import math
from typing import Optional, List, Dict, Any, Tuple

import httpx
import pandas as pd

from utils.symbols import normalize_symbol, SymbolsCache

BINANCE_FAPI = "https://fapi.binance.com"
BINANCE_SPOT = "https://api.binance.com"

_symbols_cache_fut = SymbolsCache(market="futures")
_symbols_cache_spot = SymbolsCache(market="spot")

_INVALID_TTL = 900  # 15 דקות
_invalid_cache: Dict[Tuple[str, str], float] = {}  # {(market, symbol_upper): ts_expire}

def _is_invalid(market: str, symbol: str) -> bool:
    return _invalid_cache.get((market, symbol.upper()), 0.0) > time.time()

def _mark_invalid(market: str, symbol: str) -> None:
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

def _sleep_backoff(attempt: int, base: float = 0.6, cap: float = 6.0) -> None:
    # backoff אקספוננציאלי קטן + jitter
    delay = min(cap, base * (2 ** attempt))
    jitter = delay * 0.3 * (0.5 if attempt % 2 else 1.0)
    time.sleep(delay + jitter)

def get_klines(
    symbol: str,
    interval: str,
    limit: int = 150,
    market_type: str = "futures",
) -> Optional[pd.DataFrame]:
    """
    פונקציה סינכרונית (blocking). בשכבות async משתמשים בה דרך asyncio.to_thread.
    כולל ריטריי/באק-אוף על שגיאות רשת/5xx.
    """
    market = "spot" if str(market_type).lower() == "spot" else "futures"
    sym_in = symbol.upper()

    if _is_invalid(market, sym_in):
        return None

    try:
        norm = normalize_symbol(sym_in, market=market, cache=_symbols_cache_spot if market == "spot" else _symbols_cache_fut)
    except Exception:
        _mark_invalid(market, sym_in)
        raise

    url = _endpoint_for(market)
    params = {"symbol": norm, "interval": interval, "limit": int(limit)}

    # ריטריי עד 4 ניסיונות לשגיאות זמניות
    last_err = None
    for attempt in range(4):
        try:
            with httpx.Client(timeout=6.0) as x:
                r = x.get(url, params=params)
                if r.status_code == 200:
                    data = r.json()
                    if not isinstance(data, list) or len(data) == 0:
                        return None
                    df = _to_dataframe(data)
                    if len(df) < 10:
                        return None
                    return df

                # 4xx → סמן כלא-תקין (לזמן מה) והחזר None
                if 400 <= r.status_code < 500:
                    _mark_invalid(market, sym_in)
                    return None

                # 5xx → נסה ריטריי
                last_err = f"http={r.status_code} body={(r.text or '')[:200]}"
                _sleep_backoff(attempt)
                continue

        except (httpx.ConnectError, httpx.ReadTimeout, httpx.RemoteProtocolError) as e:
            last_err = f"net={type(e).__name__}: {e}"
            _sleep_backoff(attempt)
            continue
        except Exception as e:
            last_err = f"unexpected={type(e).__name__}: {e}"
            break

    # אם התרוקנו ניסיונות – החזר None כדי שהשכבה למעלה תוכל לעשות פולבק
    return None





































