# routes/scan_top_volume.py
from __future__ import annotations

import asyncio
import logging
from typing import List, Optional, Literal, Dict, Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

logger = logging.getLogger("algogpt.scan")

# --- Auth (אם קיים utils.auth → יאכוף Bearer; אחרת פתוח) ---
try:
    from utils.auth import require_bearer_token as _raw_require_bearer  # type: ignore
    def require_bearer_token():
        return _raw_require_bearer()
except Exception:
    def require_bearer_token():
        return None

# ====== Models ======
class ScanSignal(BaseModel):
    symbol: str = Field(..., example="BTCUSDT")
    timeframe: str = Field(..., example="15m")
    side: Optional[Literal["LONG", "SHORT"]] = None
    score: float = 0.0
    note: Optional[str] = None
    details: Optional[Dict[str, Any]] = None

class ScanTopVolumeResponse(BaseModel):
    ok: bool = True
    count: int = 0
    signals: List[ScanSignal] = Field(default_factory=list)

class TopVolumeResponse(BaseModel):
    ok: bool = True
    market: str = "futures"
    quote: str = "USDT"
    limit: int = 50
    symbols: List[str] = Field(default_factory=list)

# ====== Routers ======
router = APIRouter(tags=["Scan"], dependencies=[Depends(require_bearer_token)])
router_symbols = APIRouter(tags=["Analytics"], dependencies=[Depends(require_bearer_token)])

# ====== Helpers ======
async def _get_top_symbols(market: str, quote: str, limit: int, min_qv: float) -> List[str]:
    try:
        from utils.top_volume import get_top_volume_symbols  # type: ignore
        ok, symbols = get_top_volume_symbols(
            market=market, quote=quote, limit=limit, min_quote_volume=min_qv
        )
        return symbols if ok else []
    except Exception as e:
        logger.warning("top_volume fetch failed: %s", e)
        return []

async def _scan_symbol_lite(symbol: str, timeframe: str) -> ScanSignal:
    return ScanSignal(symbol=symbol, timeframe=timeframe, side=None, score=0.0, note="lite", details=None)

async def _scan_symbol_auto(
    symbol: str,
    timeframe: str,
    bars: int,
    min_adx: float,
    ema_fast: int,
    ema_slow: int,
    adx_len: int,
) -> ScanSignal:
    # מנסה סריקה “כבדה”; אם חסר מודול/כשל → fallback ללייט
    try:
        from utils.multi_tf_scanner import analyze_symbol  # type: ignore
        r = await analyze_symbol(symbol=symbol, interval=timeframe, market_type="futures", bars=bars)
        if r:
            side = None
            sig = str(r.get("signal", "")).upper()
            if sig == "BUY":
                side = "LONG"
            elif sig == "SELL":
                side = "SHORT"
            score = 0.0
            for k in ("quality_score", "score"):
                v = r.get(k)
                if v is not None:
                    try: score = float(v); break
                    except Exception: pass
            return ScanSignal(
                symbol=symbol, timeframe=timeframe, side=side, score=score,
                note=r.get("reason") or "auto",
                details={"rsi": r.get("rsi"), "adx": r.get("adx"), "atr": r.get("atr"), "close": r.get("close")},
            )
    except Exception as e:
        logger.info("auto path (multi_tf_scanner) failed for %s: %s", symbol, e)
    return await _scan_symbol_lite(symbol, timeframe)

async def _bounded_scan(task_coro, sem: asyncio.Semaphore) -> ScanSignal:
    async with sem:
        return await task_coro

# ====== Endpoints ======
@router_symbols.get("/symbols/top-volume", response_model=TopVolumeResponse, operation_id="getTopVolumeSymbols")
async def get_top_volume_symbols_api(
    market: str = Query("futures", pattern="^(futures|spot)$"),
    quote: str = Query("USDT"),
    limit: int = Query(50, ge=1, le=200),
    min_quote_volume: float = Query(0.0),
) -> TopVolumeResponse:
    symbols = await _get_top_symbols(market, quote, limit, min_quote_volume)
    return TopVolumeResponse(ok=True, market=market, quote=quote, limit=limit, symbols=symbols)

@router.get("/scan/top-volume", response_model=ScanTopVolumeResponse, operation_id="getScanTopVolume")
async def scan_top_volume_api(
    market: str = Query("futures", pattern="^(futures|spot)$"),
    quote: str = Query("USDT"),
    limit: int = Query(50, ge=1, le=200),
    timeframe: str = Query("15m"),
    bars: int = Query(200, ge=50, le=1500),
    trending_only: bool = Query(False),
    min_adx: float = Query(20.0, ge=5.0, le=60.0),
    ema_fast: int = Query(21, ge=3, le=200),
    ema_slow: int = Query(50, ge=5, le=400),
    adx_len: int = Query(14, ge=5, le=50),
    st_period: int = Query(10, ge=5, le=50),
    st_factor: float = Query(3.0, ge=1.0, le=10.0),
    ich_conv: int = Query(9, ge=5, le=50),
    ich_base: int = Query(26, ge=10, le=100),
    ich_span_b: int = Query(52, ge=20, le=200),
    ms_lookback: int = Query(5, ge=2, le=20),
    ms_pivot_span: int = Query(3, ge=1, le=10),
    concurrency: int = Query(16, ge=2, le=64),
    mode: Literal["lite", "auto"] = Query("lite", description="lite=בטוח, auto=ניסיון סריקה מלאה"),
) -> ScanTopVolumeResponse:
    symbols = await _get_top_symbols(market, quote, limit, min_qv=0.0)
    if not symbols:
        return ScanTopVolumeResponse(ok=True, count=0, signals=[])
    sem = asyncio.Semaphore(concurrency)
    tasks = []
    for sym in symbols:
        coro = _scan_symbol_auto(sym, timeframe, bars, min_adx, ema_fast, ema_slow, adx_len) if mode == "auto" \
               else _scan_symbol_lite(sym, timeframe)
        tasks.append(asyncio.create_task(_bounded_scan(coro, sem)))
    signals: List[ScanSignal] = []
    for t in asyncio.as_completed(tasks):
        try:
            sig = await t
            if trending_only and sig.details and isinstance(sig.details.get("adx"), (int, float)):
                try:
                    if float(sig.details["adx"]) < float(min_adx):
                        continue
                except Exception:
                    pass
            signals.append(sig)
        except Exception as e:
            logger.warning("scan task failed (ignored): %s", e)
    return ScanTopVolumeResponse(ok=True, count=len(signals), signals=signals)



















