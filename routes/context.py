# routes/context.py
from __future__ import annotations
from fastapi import APIRouter, Query, HTTPException, Request, Depends
from pydantic import BaseModel
from typing import Optional, Dict, Any
import os, time, math
import pandas as pd
import httpx

# אבטחה: Bearer בלבד (GET); אם אין לך utils.auth – החלף ל-noop
try:
    from utils.auth import require_bearer_token
except Exception:
    def require_bearer_token():
        return None

from utils.indicators import rsi as rsi_fn, adx as adx_fn, atr as atr_fn, ema as ema_fn

router = APIRouter(prefix="", tags=["Context"], dependencies=[Depends(require_bearer_token)])

FUTURES_BASE = os.getenv("BINANCE_FUTURES_HTTP_BASE", "https://fapi.binance.com")
CTX_CACHE_TTL = int(os.getenv("CONTEXT_TTL_SECONDS", "20"))   # Cache קצר כדי לא לקרוע את הבורסה
MAX_LIMIT = 200

_cache: Dict[str, tuple[float, dict]] = {}  # key -> (ts, data)

def _now() -> float:
    return time.time()

def _in_cache(key: str) -> Optional[dict]:
    item = _cache.get(key)
    if not item:
        return None
    ts, data = item
    if (_now() - ts) <= CTX_CACHE_TTL:
        return data
    return None

def _save_cache(key: str, data: dict) -> None:
    _cache[key] = (_now(), data)

# rate limit פר IP
_rate: Dict[str, list[float]] = {}
def _rl(ip: str, limit=60, window=60) -> bool:
    now = _now()
    calls = [t for t in _rate.get(ip, []) if now - t < window]
    if len(calls) >= limit:
        return False
    calls.append(now)
    _rate[ip] = calls
    return True

async def _fetch_klines(symbol: str, interval: str, limit: int) -> pd.DataFrame:
    url = f"{FUTURES_BASE}/fapi/v1/klines"
    params = {"symbol": symbol.upper(), "interval": interval, "limit": int(limit)}
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(url, params=params)
        r.raise_for_status()
        arr = r.json()
    if not arr:
        return pd.DataFrame()
    cols = ["open_time","open","high","low","close","volume","close_time","qv","nTrades","taker_base","taker_quote","x"]
    df = pd.DataFrame(arr, columns=cols[:len(arr[0])])
    for c in ("open","high","low","close","volume"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df[["open","high","low","close","volume"]]

class ContextOut(BaseModel):
    symbol: str
    interval: str
    price: float
    rsi: float | None = None
    adx: float | None = None
    atr: float | None = None
    ema_21: float | None = None
    vol_15m_est: float | None = None   # הערכת תנועה לדקה (גסה)
    filters: Dict[str, Any] = {}       # מקום לדגלי סינון שלך
    ts: int

@router.get("/context", response_model=ContextOut)
async def get_context(
    request: Request,
    symbol: str = Query(..., min_length=5, max_length=20),
    interval: str = Query("15m"),
    limit: int = Query(120, ge=60, le=MAX_LIMIT),
    include_filters: bool = Query(True, description="החזרת דגלי סינון פנימיים אם יש"),
):
    # Rate limit
    if not _rl(request.client.host):
        raise HTTPException(429, "Rate limit exceeded")

    key = f"{symbol.upper()}|{interval}|{limit}|{include_filters}"
    cached = _in_cache(key)
    if cached:
        return cached

    df = await _fetch_klines(symbol, interval, limit)
    if df.empty:
        raise HTTPException(404, "no data")

    # חישוב מינימלי ומהיר
    close = pd.to_numeric(df["close"], errors="coerce")
    price = float(close.iloc[-1])

    rsi_s = rsi_fn(close, 14)
    adx_s = adx_fn(df, 14)
    atr_s = atr_fn(df, 14)
    ema21 = ema_fn(close, 21)

    # safe getters
    def last_val(s: pd.Series) -> Optional[float]:
        try:
            v = float(s.dropna().iloc[-1])
            if math.isfinite(v):
                return round(v, 4)
            return None
        except Exception:
            return None

    # הערכת תנודתיות לדקה (VERY LIGHT): סטיית תקן על שינויי close (נורמליזציה גסה)
    diffs = close.diff().abs().dropna()
    vol_15m_est = round(float(diffs.tail(20).mean() or 0.0), 6) if not diffs.empty else None

    data = ContextOut(
        symbol=symbol.upper(),
        interval=interval,
        price=round(price, 6),
        rsi=last_val(rsi_s),
        adx=last_val(adx_s),
        atr=last_val(atr_s),
        ema_21=last_val(ema21),
        vol_15m_est=vol_15m_est,
        filters={},   # כאן תוכל להכניס דגלים משלך בעתיד
        ts=int(time.time()),
    ).model_dump()

    _save_cache(key, data)
    return data
