# routes/scan_top_volume.py
from __future__ import annotations
import os
from typing import List, Dict, Any, Optional, Iterable
from fastapi import APIRouter, Query, Depends
import httpx
import numpy as np

from utils.auth import require_bearer_token

router = APIRouter(tags=["Scanner"], dependencies=[Depends(require_bearer_token)])
router_symbols = APIRouter(tags=["Scanner"], dependencies=[Depends(require_bearer_token)])

_FAPI = os.getenv("BINANCE_FUTURES_HTTP_BASE", "https://fapi.binance.com").rstrip("/")
_SCAN_MAX_LIMIT = int(os.getenv("SCAN_MAX_LIMIT", "20"))

# ---- indicators (NumPy only) ----
def _ema(arr: np.ndarray, period: int) -> np.ndarray:
    alpha = 2.0 / (period + 1.0)
    out = np.empty_like(arr, dtype=float)
    out[0] = arr[0]
    for i in range(1, len(arr)):
        out[i] = alpha * arr[i] + (1 - alpha) * out[i-1]
    return out

def _rma(arr: np.ndarray, period: int) -> np.ndarray:
    out = np.empty_like(arr, dtype=float)
    out[0] = arr[:period].mean()
    alpha = 1.0 / period
    for i in range(1, len(arr)):
        out[i] = (out[i-1] * (1 - alpha)) + alpha * arr[i]
    return out

def _rsi(close: np.ndarray, period: int = 14) -> np.ndarray:
    diff = np.diff(close, prepend=close[0])
    gain = np.where(diff > 0, diff, 0.0)
    loss = np.where(diff < 0, -diff, 0.0)
    avg_gain = _rma(gain, period)
    avg_loss = _rma(loss, period)
    rs = np.where(avg_loss == 0, np.inf, avg_gain / avg_loss)
    return 100.0 - (100.0 / (1.0 + rs))

def _atr(high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int = 14) -> np.ndarray:
    prev_close = np.roll(close, 1); prev_close[0] = close[0]
    tr = np.maximum.reduce([high - low, np.abs(high - prev_close), np.abs(low - prev_close)])
    return _rma(tr, period)

def _adx(high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int = 14) -> np.ndarray:
    up_move = high[1:] - high[:-1]
    down_move = low[:-1] - low[1:]
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
    tr = _atr(high, low, close, period)
    plus_dm_full = np.concatenate([[0.0], plus_dm])
    minus_dm_full = np.concatenate([[0.0], minus_dm])
    plus_dm_rma = _rma(plus_dm_full, period)
    minus_dm_rma = _rma(minus_dm_full, period)
    plus_di = 100.0 * np.where(tr == 0, 0.0, plus_dm_rma / tr)
    minus_di = 100.0 * np.where(tr == 0, 0.0, minus_dm_rma / tr)
    dx = 100.0 * np.where((plus_di + minus_di) == 0, 0.0, np.abs(plus_di - minus_di) / (plus_di + minus_di))
    return _rma(dx, period)

# ---- binance helpers ----
async def _fetch_24h() -> List[Dict[str, Any]]:
    url = f"{_FAPI}/fapi/v1/ticker/24hr"
    async with httpx.AsyncClient(timeout=8.0) as client:
        r = await client.get(url)
        r.raise_for_status()
        data = r.json()
        return data if isinstance(data, list) else []

def _top_symbols_24h(tickers: List[Dict[str, Any]], quote: str, limit: int) -> List[str]:
    q = quote.upper()
    rows = [t for t in tickers if isinstance(t, dict) and str(t.get("symbol","")).endswith(q)]
    def _qv(v: Any) -> float:  # type: ignore[name-defined]
        try:
            return float(v.get("quoteVolume", 0.0))  # type: ignore[attr-defined]
        except Exception:
            return 0.0
    rows.sort(key=_qv, reverse=True)
    return [r["symbol"] for r in rows[:max(1, int(limit))]]

async def _klines(symbol: str, interval: str, limit: int) -> Optional[List[List[Any]]]:
    url = f"{_FAPI}/fapi/v1/klines"
    params = {"symbol": symbol, "interval": interval, "limit": int(limit)}
    async with httpx.AsyncClient(timeout=8.0) as client:
        r = await client.get(url, params=params)
        r.raise_for_status()
        data = r.json()
        return data if isinstance(data, list) else None

def _analyze_rows(rows: List[List[Any]], interval: str) -> Dict[str, Any]:
    idx_open, idx_high, idx_low, idx_close, idx_vol = 1, 2, 3, 4, 5
    close = np.array([float(r[idx_close]) for r in rows], dtype=float)
    high  = np.array([float(r[idx_high])  for r in rows], dtype=float)
    low   = np.array([float(r[idx_low])   for r in rows], dtype=float)
    vol   = float(rows[-1][idx_vol])

    rsi_last = float(_rsi(close, 14)[-1])
    ema21 = float(_ema(close, 21)[-1])
    ema50 = float(_ema(close, 50)[-1])
    adx14 = float(_adx(high, low, close, 14)[-1])

    trend = "UP" if ema21 >= ema50 else "DOWN"
    direction = None
    note = None
    if adx14 >= 20:
        if close[-1] >= ema21 >= ema50:
            direction, note = "LONG", "EMA21>=EMA50 & ADX>=20"
        elif close[-1] <= ema21 <= ema50:
            direction, note = "SHORT", "EMA21<=EMA50 & ADX>=20"
        else:
            note = "structure mixed"
    else:
        note = "ADX<20"

    quality = 5.0
    if direction:
        quality = 6.5 + min(3.0, max(0.0), (adx14 - 20.0) * 0.1)

    return {
        "timeframe": interval,
        "side": "BUY" if direction == "LONG" else ("SELL" if direction == "SHORT" else None),
        "score": round(quality, 2),
        "note": note,
        "details": {
            "trend": trend, "rsi": round(rsi_last, 2), "adx": round(adx14, 2),
            "ema21": round(ema21, 6), "ema50": round(ema50, 6),
            "close": round(float(close[-1]), 6), "volume": vol
        }
    }

# ---- helpers ----
def _clamp_limit(n: int) -> int:
    return max(1, min(_SCAN_MAX_LIMIT, n))

def _parse_fields(fields: Optional[str]) -> Optional[List[str]]:
    if not fields:
        return None
    return [f.strip() for f in fields.split(",") if f.strip()]

def _select_fields(item: Dict[str, Any], fields: Optional[Iterable[str]], compact: bool) -> Dict[str, Any]:
    if compact and not fields:
        fields = ("symbol", "timeframe", "side", "score", "note")
    if fields:
        return {k: item.get(k) for k in fields if k in item}
    return item

@router_symbols.get("/symbols/top-volume", operation_id="getSymbolsTopVolume")
async def get_symbols_top_volume(
    market: str = Query("futures"),
    quote: str = Query("USDT"),
    limit: int = Query(5, ge=1, le=100),
) -> Dict[str, Any]:
    try:
        tickers = await _fetch_24h()
        symbols = _top_symbols_24h(tickers, quote=quote, limit=limit)
        return {"ok": True, "market": market, "quote": quote, "limit": limit, "symbols": symbols}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}

@router.get("/scan/top-volume", operation_id="scanTopVolume")
async def scan_top_volume(
    market: str = Query("futures"),
    quote: str = Query("USDT"),
    limit: int = Query(5, ge=1, le=100),
    timeframe: str = Query("15m"),
    kline_limit: int = Query(200, ge=60, le=1000),
    symbol: Optional[str] = Query(None, description="Filter for a single symbol"),
    fields: Optional[str] = Query(None, description="CSV fields to return (e.g. symbol,score,note)"),
    compact: bool = Query(True, description="Return minimal fields by default"),
) -> Dict[str, Any]:
    try:
        limit = _clamp_limit(limit)
        tickers = await _fetch_24h()
        symbols = _top_symbols_24h(tickers, quote=quote, limit=limit)
        if symbol:
            s = symbol.upper().strip()
            symbols = [x for x in symbols if x.upper() == s] or [s]

        results: List[Dict[str, Any]] = []
        for sym in symbols:
            try:
                rows = await _klines(sym, timeframe, kline_limit)
                if not rows or len(rows) < 60:
                    results.append({"symbol": sym, "timeframe": timeframe, "side": None, "score": 0.0, "note": "lite (not enough data)", "details": None})
                    continue
                res = _analyze_rows(rows, timeframe)
                results.append({"symbol": sym, **res})
            except Exception as e:
                results.append({"symbol": sym, "timeframe": timeframe, "side": None, "score": 0.0, "note": f"lite (analyze-fallback: {type(e).__name__})", "details": None})

        wanted = _parse_fields(fields)
        results = [_select_fields(r, wanted, compact) for r in results]

        out: Dict[str, Any] = {"ok": True, "count": len(results), "signals": results}
        if compact:
            out["mode"] = "compact"
        return out
    except Exception as e:
        return {"ok": False, "count": 0, "signals": [], "fallback": f"lite ({type(e).__name__})"}

@router.get("/scan", operation_id="scanSingle")
async def scan_single(
    symbol: str = Query(...),
    timeframe: str = Query("15m"),
    market: str = Query("futures"),
    fields: Optional[str] = Query(None),
    compact: bool = Query(True),
) -> Dict[str, Any]:
    return await scan_top_volume(market=market, quote="USDT", limit=5, timeframe=timeframe,
                                 kline_limit=200, symbol=symbol, fields=fields, compact=compact)


























