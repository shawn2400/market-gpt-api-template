# routes/scan_top_volume.py
from __future__ import annotations

import os
import logging
from typing import List, Dict, Any, Optional

import numpy as np
import httpx
from fastapi import APIRouter, Query, Depends, HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger("algogpt.scan_top_volume")

# =====================
# Auth (fallback-safe)
# =====================
try:
    from utils.auth import require_bearer_token  # type: ignore
except Exception:
    def require_bearer_token():
        return None

# =====================
# SymbolsCache (fallback-safe)
# =====================
class _SymbolsCacheFallback:
    def __init__(self, market: str = "futures"):
        self.market = market
        self._ok = False
    def ensure(self) -> None:
        self._ok = True
    def has(self, symbol: str) -> bool:
        return True

try:
    from utils.symbols import SymbolsCache as _RealSymbolsCache  # type: ignore
    SymbolsCache = _RealSymbolsCache  # type: ignore
except Exception:
    SymbolsCache = _SymbolsCacheFallback  # type: ignore
    logger.warning("[scan_top_volume] utils.symbols.SymbolsCache not available, using fallback (no filtering)")

# =====================
# APIRouter
# =====================
router = APIRouter(
    prefix="/scan",
    tags=["Scanner"],
    dependencies=[Depends(require_bearer_token)],
)

# =====================
# Config
# =====================
_FAPI = os.getenv("BINANCE_FUTURES_HTTP_BASE", "https://fapi.binance.com").rstrip("/")
_SCAN_MAX_LIMIT = min(int(os.getenv("SCAN_MAX_LIMIT", "10")), 10)

# =====================
# Models
# =====================
class IndicatorDetails(BaseModel):
    trend: str
    rsi: float
    adx: float
    ema21: float
    ema50: float
    close: float
    volume: float

class ScanSignal(BaseModel):
    symbol: str
    timeframe: str
    side: Optional[str]
    score: float
    note: Optional[str]
    details: Optional[IndicatorDetails] = None

class ScanResponse(BaseModel):
    ok: bool = True
    count_total: int
    returned: int
    signals: List[ScanSignal] = Field(default_factory=list)
    mode: Optional[str] = None
    error: Optional[str] = None

class SymbolListResponse(BaseModel):
    ok: bool = True
    market: str
    quote: str
    count_total: int
    returned: int
    symbols: List[str]

# =====================
# TA helpers (NumPy)
# =====================
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

# =====================
# Binance helpers
# =====================
async def _fetch_24h() -> List[Dict[str, Any]]:
    url = f"{_FAPI}/fapi/v1/ticker/24hr"
    async with httpx.AsyncClient(timeout=8.0) as client:
        r = await client.get(url)
        r.raise_for_status()
        data = r.json()
        return data if isinstance(data, list) else []

def _clamp_limit(n: int) -> int:
    return max(1, min(_SCAN_MAX_LIMIT, n))

def _top_symbols_24h(
    tickers: List[Dict[str, Any]], quote: str, limit: int, market: str
) -> List[str]:
    q = (quote or "USDT").upper()
    rows = [t for t in tickers if isinstance(t, dict) and str(t.get("symbol", "")).endswith(q)]

    def _qv(v: Any) -> float:
        try:
            return float(v.get("quoteVolume", 0.0))
        except Exception:
            return 0.0

    rows.sort(key=_qv, reverse=True)
    symbols = [r["symbol"] for r in rows[:_clamp_limit(limit)]]

    sym_cache = SymbolsCache(market=market)  # type: ignore
    try:
        sym_cache.ensure()
    except Exception:
        pass

    valid_symbols = []
    for s in symbols:
        try:
            if sym_cache.has(s):
                valid_symbols.append(s)
        except Exception:
            valid_symbols.append(s)

    dropped = set(symbols) - set(valid_symbols)
    if dropped:
        logger.info("[scan_top_volume] dropped invalid symbols: %s", ", ".join(sorted(dropped))[:400])

    return valid_symbols

async def _klines(symbol: str, interval: str, limit: int) -> Optional[List[List[Any]]]:
    url = f"{_FAPI}/fapi/v1/klines"
    params = {"symbol": symbol, "interval": interval, "limit": int(limit)}
    async with httpx.AsyncClient(timeout=8.0) as client:
        r = await client.get(url, params=params)
        r.raise_for_status()
        data = r.json()
        return data if isinstance(data, list) else None

def _analyze_rows(rows: List[List[Any]], interval: str, symbol: str) -> ScanSignal:
    idx_high, idx_low, idx_close, idx_vol = 2, 3, 4, 5
    close = np.array([float(r[idx_close]) for r in rows], dtype=float)
    high  = np.array([float(r[idx_high])  for r in rows], dtype=float)
    low   = np.array([float(r[idx_low])   for r in rows], dtype=float)
    vol   = float(rows[-1][idx_vol])

    rsi_last = float(_rsi(close, 14)[-1])
    ema21 = float(_ema(close, 21)[-1])
    ema50 = float(_ema(close, 50)[-1])
    adx14 = float(_adx(high, low, close, 14)[-1])

    trend = "UP" if ema21 >= ema50 else "DOWN"
    direction, note = None, None
    if adx14 >= 20:
        if close[-1] >= ema21 >= ema50:
            direction, note = "LONG", "EMA21>=EMA50 & ADX>=20"
        elif close[-1] <= ema21 <= ema50:
            direction, note = "SHORT", "EMA21<=EMA50 & ADX>=20"
        else:
            note = "structure mixed"
    else:
        note = "ADX<20"

    score = 5.0
    if direction:
        score = 6.5 + min(3.0, max(0.0, (adx14 - 20.0) * 0.1))

    return ScanSignal(
        symbol=symbol,
        timeframe=interval,
        side="BUY" if direction == "LONG" else ("SELL" if direction == "SHORT" else None),
        score=round(score, 2),
        note=note,
        details=IndicatorDetails(
            trend=trend,
            rsi=round(rsi_last, 2),
            adx=round(adx14, 2),
            ema21=round(ema21, 6),
            ema50=round(ema50, 6),
            close=round(float(close[-1]), 6),
            volume=vol,
        ),
    )

# =====================
# Optional notifier (Telegram)
# =====================
def _notify_telegram(chat_id: str, text: str, retries: int = 2) -> bool:
    sender = None
    try:
        from integrations.telegram import send_message_safe as sender  # type: ignore
    except Exception:
        try:
            from utils.telegram_notifier import send_message_safe as sender  # type: ignore
        except Exception:
            sender = None

    if not sender:
        logger.info("[scan_top_volume] telegram sender not available")
        return False

    ok = False
    for _ in range(max(1, retries)):
        try:
            ok = bool(sender(chat_id, text))
            if ok:
                break
        except Exception:
            ok = False
    return ok

# =====================
# Routes
# =====================
@router.get(
    "/symbols/top-volume",
    response_model=SymbolListResponse,
    summary="Top-volume symbols (USDT)",
)
async def get_symbols_top_volume(
    market: str = Query("futures", description="Binance FAPI market"),
    quote: str = Query("USDT"),
    limit: int = Query(5, ge=1, le=100),
) -> SymbolListResponse:
    tickers = await _fetch_24h()
    symbols = _top_symbols_24h(tickers, quote=quote, limit=limit, market=market)
    return SymbolListResponse(
        ok=True,
        market=market,
        quote=quote,
        count_total=len(symbols),
        returned=len(symbols),
        symbols=symbols,
    )

@router.get(
    "/top-volume",
    response_model=ScanResponse,
    summary="Scan top-volume list and compute compact TA score",
)
async def scan_top_volume(
    market: str = Query("futures", description="Binance FAPI"),
    quote: str = Query("USDT"),
    limit: int = Query(5, ge=1, le=100),
    timeframe: str = Query("15m"),
    kline_limit: int = Query(200, ge=60, le=1000),
    symbol: Optional[str] = Query(None, description="If provided, scan this symbol only"),
    threshold: float = Query(6.0, description="Only alerts (notify) for hits >= threshold"),
    notify: Optional[str] = Query(None, description="e.g. 'telegram'"),
    chat_id: Optional[str] = Query(None, description="Telegram chat id for notify"),
) -> ScanResponse:
    try:
        eff_limit = _clamp_limit(limit)
        tickers = await _fetch_24h()
        symbols = _top_symbols_24h(tickers, quote=quote, limit=eff_limit, market=market)
        if symbol:
            s = symbol.upper().strip()
            symbols = [x for x in symbols if x.upper() == s] or [s]

        results: List[ScanSignal] = []
        for sym in symbols:
            try:
                rows = await _klines(sym, timeframe, kline_limit)
                if not rows or len(rows) < 60:
                    results.append(
                        ScanSignal(symbol=sym, timeframe=timeframe, side=None, score=0.0, note="not enough data")
                    )
                    continue
                res = _analyze_rows(rows, timeframe, sym)
                results.append(res)
            except Exception:
                results.append(
                    ScanSignal(symbol=sym, timeframe=timeframe, side=None, score=0.0, note="analyze error")
                )

        resp = ScanResponse(
            ok=True,
            count_total=len(symbols),
            returned=len(results),
            signals=results,
            mode="compact",
        )

        # Notify (optional)
        hits = [s for s in results if s.score >= float(threshold)]
        if notify == "telegram" and chat_id and hits:
            lines = [
                f"• {h.symbol} {h.timeframe} score={h.score} side={h.side or '-'} ({h.note or ''})"
                for h in hits
            ]
            text = "🚦 Scan hits ≥{:.1f}\n".format(threshold) + "\n".join(lines)
            sent = _notify_telegram(chat_id, text, retries=2)
            logger.info("[scan_top_volume] telegram notify sent=%s hits=%d", sent, len(hits))

        return resp

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("[scan_top_volume] failed: %s", e)
        return ScanResponse(ok=False, count_total=0, returned=0, signals=[], error=f"{type(e).__name__}: {e}")

@router.get(
    "/single",
    response_model=ScanResponse,
    summary="Scan a single symbol (compact TA)",
)
async def scan_single(
    symbol: str = Query(..., description="e.g. BTCUSDT"),
    timeframe: str = Query("15m"),
    market: str = Query("futures"),
    threshold: float = Query(6.0),
    notify: Optional[str] = Query(None),
    chat_id: Optional[str] = Query(None),
) -> ScanResponse:
    return await scan_top_volume(
        market=market,
        quote="USDT",
        limit=1,
        timeframe=timeframe,
        kline_limit=200,
        symbol=symbol,
        threshold=threshold,
        notify=notify,
        chat_id=chat_id,
    )

__all__ = ["router"]


































