# routes/ai_analyze.py
from __future__ import annotations
import os
from typing import Dict, Any, List, Optional, Iterable
from fastapi import APIRouter, Query, Depends
import httpx
import numpy as np

from utils.auth import require_bearer_token

# -------------------------------------------------
# Router
# -------------------------------------------------
router = APIRouter(tags=["AI"], dependencies=[Depends(require_bearer_token)])

_FAPI = os.getenv("BINANCE_FUTURES_HTTP_BASE", "https://fapi.binance.com").rstrip("/")

# -------------------------------------------------
# Indicators (NumPy only)
# -------------------------------------------------
def _ema(arr: np.ndarray, period: int) -> np.ndarray:
    alpha = 2.0 / (period + 1.0)
    out = np.empty_like(arr, dtype=float)
    out[0] = arr[0]
    for i in range(1, len(arr)):
        out[i] = alpha * arr[i] + (1 - alpha) * out[i - 1]
    return out

def _rma(arr: np.ndarray, period: int) -> np.ndarray:
    out = np.empty_like(arr, dtype=float)
    out[0] = arr[:period].mean()
    alpha = 1.0 / period
    for i in range(1, len(arr)):
        out[i] = (out[i - 1] * (1 - alpha)) + alpha * arr[i]
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
    prev_close = np.roll(close, 1)
    prev_close[0] = close[0]
    tr = np.maximum.reduce([
        high - low,
        np.abs(high - prev_close),
        np.abs(low - prev_close),
    ])
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
    dx = 100.0 * np.where(
        (plus_di + minus_di) == 0,
        0.0,
        np.abs(plus_di - minus_di) / (plus_di + minus_di),
    )
    return _rma(dx, period)

# -------------------------------------------------
# Binance fetcher
# -------------------------------------------------
async def _fetch_klines(symbol: str, interval: str = "15m", limit: int = 200) -> List[List[Any]]:
    url = f"{_FAPI}/fapi/v1/klines"
    params = {"symbol": symbol.upper(), "interval": interval, "limit": int(limit)}
    async with httpx.AsyncClient(timeout=8.0) as client:
        r = await client.get(url, params=params)
        r.raise_for_status()
        data = r.json()
        if not isinstance(data, list):
            raise RuntimeError("unexpected klines shape")
        return data

# -------------------------------------------------
# Analyzer (NumPy only)
# -------------------------------------------------
def _analyze_numpy(rows: List[List[Any]], interval: str) -> Dict[str, Any]:
    idx_open, idx_high, idx_low, idx_close, idx_vol = 1, 2, 3, 4, 5
    close = np.array([float(r[idx_close]) for r in rows], dtype=float)
    high  = np.array([float(r[idx_high]) for r in rows], dtype=float)
    low   = np.array([float(r[idx_low]) for r in rows], dtype=float)
    vol   = float(rows[-1][idx_vol])

    rsi_last = float(_rsi(close, 14)[-1])
    ema_fast = float(_ema(close, 21)[-1])
    ema_slow = float(_ema(close, 50)[-1])
    atr_last = float(_atr(high, low, close, 14)[-1])
    adx_last = float(_adx(high, low, close, 14)[-1])
    c_last   = float(close[-1])

    trend = "UP" if ema_fast >= ema_slow else "DOWN"
    direction, note = None, None
    if adx_last >= 20:
        if c_last >= ema_fast >= ema_slow:
            direction, note = "LONG", "EMA21>=EMA50 & ADX>=20"
        elif c_last <= ema_fast <= ema_slow:
            direction, note = "SHORT", "EMA21<=EMA50 & ADX>=20"
        else:
            note = "structure mixed"
    else:
        note = "ADX<20"

    quality = 5.0
    if direction:
        quality = 6.5 + min(3.0, max(0.0, (adx_last - 20.0) * 0.1))

    return {
        "symbol": None,
        "market": "futures",
        "interval": interval,
        "frames": [interval],
        "trend": trend,
        "direction": direction,
        "rsi": round(rsi_last, 2),
        "adx": round(adx_last, 2),
        "volume": vol,
        "quality_score": round(float(quality), 2),
        "signal": "BUY" if direction == "LONG" else ("SELL" if direction == "SHORT" else "HOLD"),
        "confidence": int(min(100, max(0, (quality / 10.0) * 100))),
        "reason": note,
        "close": c_last,
        "atr": round(atr_last, 6),
    }

# -------------------------------------------------
# Helpers
# -------------------------------------------------
def _parse_fields(fields: Optional[str]) -> Optional[List[str]]:
    if not fields:
        return None
    return [f.strip() for f in fields.split(",") if f.strip()]

def _select_fields(item: Dict[str, Any], fields: Optional[Iterable[str]], compact: bool) -> Dict[str, Any]:
    if compact and not fields:
        fields = ("symbol","market","interval","signal","quality_score","confidence","reason","close","atr")
    if fields:
        return {k: item.get(k) for k in fields if k in item}
    return item

# -------------------------------------------------
# Route
# -------------------------------------------------
@router.get("/ai/manual-scan", operation_id="getAiManualScan")
async def ai_manual_scan(
    symbol: str = Query(..., description="e.g. BTCUSDT"),
    interval: str = Query("15m"),
    limit: int = Query(200, ge=50, le=1500),
    fields: Optional[str] = Query(None),
    compact: bool = Query(True),
) -> Dict[str, Any]:
    symbol = symbol.upper().strip()
    try:
        rows = await _fetch_klines(symbol, interval=interval, limit=limit)
        if not rows or len(rows) < 60:
            base = {
                "symbol": symbol,
                "market": "futures",
                "interval": interval,
                "signal": "HOLD",
                "reason": "lite (not enough data)"
            }
            return {"symbol": symbol, "results": _select_fields(base, _parse_fields(fields), compact)}

        res = _analyze_numpy(rows, interval)
        res["symbol"] = symbol
        return {"symbol": symbol, "results": _select_fields(res, _parse_fields(fields), compact)}

    except Exception as e:
        base = {
            "symbol": symbol, "market": "futures", "interval": interval,
            "frames": [interval], "trend": None, "direction": None,
            "rsi": None, "adx": None, "volume": None, "quality_score": None,
            "signal": None, "confidence": None, "close": None, "atr": None,
            "reason": f"lite (analyze-fallback: {type(e).__name__})"
        }
        return {"symbol": symbol, "results": _select_fields(base, _parse_fields(fields), compact)}










