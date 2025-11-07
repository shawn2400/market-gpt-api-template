from __future__ import annotations
import asyncio, random, os, hashlib, logging
from typing import List, Dict, Any
import pandas as pd

from utils.symbols import normalize_symbol
from utils.http_client import safe_get

# ========== VERSION TRACKING & TELEMETRY ==========
# This helps detect module caching issues where workers load stale code
KLINES_VERSION = "3.0.0"  # Bump this when making changes to verify workers load new code
KLINES_MODULE_FILE = __file__
KLINES_FIX_DESCRIPTION = "No startTime caching - always fetch latest N candles"

logger = logging.getLogger(__name__)

def _get_module_hash() -> str:
    """Calculate hash of this module for cache verification"""
    try:
        with open(__file__, 'rb') as f:
            return hashlib.sha256(f.read()).hexdigest()[:8]
    except Exception:
        return "unknown"

# Log module version on import for debugging caching issues
logger.info(f"🔧 get_klines module loaded: VERSION={KLINES_VERSION}, FILE={KLINES_MODULE_FILE}, HASH={_get_module_hash()}, FIX={KLINES_FIX_DESCRIPTION}")

BINANCE_FAPI = os.getenv("BINANCE_FUTURES_HTTP_BASE", "https://fapi.binance.com").rstrip("/")
BINANCE_SPOT = os.getenv("BINANCE_SPOT_HTTP_BASE", "https://api.binance.com").rstrip("/")

_BASE_PAUSE_MS = int(os.getenv("KLINES_BASE_PAUSE_MS", "60"))
_JITTER_MS_MIN = int(os.getenv("KLINES_JITTER_MS_MIN", "20"))
_JITTER_MS_MAX = int(os.getenv("KLINES_JITTER_MS_MAX", "120"))

# CRITICAL FIX v3.0.0: DISABLE klines caching completely
# The _last_ts cache causes "Insufficient klines data (1 candles)" when:
# - Requesting limit=200 with startTime from 30min ago
# - Binance interprets this as incremental update and returns only 1 new candle
# Solution: No caching = always get latest N candles
_last_ts: Dict[str, int] = {}  # Keep dict for compatibility but never use it

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
    # CRITICAL FIX: Never use _last_ts cache - it causes "Insufficient klines (1 candles)" issue
    # Always fetch latest N candles without startTime to avoid Binance incremental update logic
    df = pd.DataFrame()
    
    try:
        df = await _rest_klines(symbol, interval, limit, "futures", None)  # No startTime!
    except Exception:
        df = pd.DataFrame()
    
    if df.empty:
        try:
            df = await _rest_klines(symbol, interval, limit, "spot", None)  # No startTime!
        except Exception:
            df = pd.DataFrame()
    
    # DO NOT update _last_ts cache - disabled permanently
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



















































