# routes/multi_scan.py
from __future__ import annotations
from fastapi import APIRouter, Query, HTTPException, Request
from typing import List, Dict, Any, Optional
import os, asyncio, logging

import pandas as pd
import httpx
from pydantic import BaseModel, Field

from utils.indicators import prepare_indicators_for_backtest
from utils.ai_analysis import analyze_with_ai
from utils.rate_limit import allow as rl_allow

logger = logging.getLogger("algogpt.scan")

FUTURES_BASE = os.getenv("BINANCE_FUTURES_HTTP_BASE", "https://fapi.binance.com").rstrip("/")
SCAN_HTTP_TIMEOUT = float(os.getenv("SCAN_HTTP_TIMEOUT", "10.0"))
SCAN_MAX_SYMBOLS = int(os.getenv("SCAN_MAX_SYMBOLS", "60"))  # ביטחון נגד עומס
router = APIRouter(prefix="/scan", tags=["Scan"])

# ========= Binance helper (async, לא חוסם) =========
async def _fetch_klines(symbol: str, interval: str = "15m", limit: int = 200) -> pd.DataFrame:
    sym = symbol.strip().upper()
    if not sym.endswith("USDT"):
        sym += "USDT"
    url = f"{FUTURES_BASE}/fapi/v1/klines"
    params = {"symbol": sym, "interval": interval, "limit": int(limit)}
    async with httpx.AsyncClient(timeout=SCAN_HTTP_TIMEOUT) as cli:
        r = await cli.get(url, params=params)
        r.raise_for_status()
        arr = r.json()

    if not arr:
        return pd.DataFrame()

    cols = [
        "open_time","open","high","low","close","volume",
        "close_time","qv","nTrades","taker_base","taker_quote","x"
    ]
    # מקצרים למספר העמודות המוחזר בפועל
    df = pd.DataFrame(arr, columns=cols[:len(arr[0])])
    for c in ("open","high","low","close","volume"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df[["open","high","low","close","volume"]]

# ========= Models =========
class IndicatorSet(BaseModel):
    class Config:
        extra = "ignore"
    try:
        from pydantic import ConfigDict
        model_config = ConfigDict(extra="ignore")  # type: ignore
    except Exception:
        pass

    rsi: float | None = None
    ema_21: float | None = None
    adx: float | None = None
    atr: float | None = None
    vwap_trend: bool | None = None
    ema_50: float | None = None
    macd: float | None = None
    macd_signal: float | None = None
    macd_hist: float | None = None
    bb_mid: float | None = None
    bb_upper: float | None = None
    bb_lower: float | None = None

class ScanSignal(BaseModel):
    symbol: str
    interval: str
    indicators: IndicatorSet | None = None
    analysis: str | None = None
    ok: bool = True
    error: str | None = None

class MultiScanResponse(BaseModel):
    ok: bool = True
    count_total: int
    returned: int
    signals: List[ScanSignal] = Field(default_factory=list)
    error: str | None = None

# ========= Helpers =========
async def _maybe_analyze_with_ai(payload: Dict[str, Any]) -> Dict[str, Any]:
    # תומך גם בפונקציה sync וגם async
    if asyncio.iscoroutinefunction(analyze_with_ai):
        return await analyze_with_ai(payload)  # type: ignore
    return await asyncio.to_thread(analyze_with_ai, payload)

# ========= Endpoints =========
@router.get("/multi", response_model=MultiScanResponse, summary="Multi-symbol scan (CSV query)")
async def scan_symbols(
    symbols: str = Query(..., description="CSV e.g. BTCUSDT,ETHUSDT (או BTC,ETH)"),
    interval: str = Query("15m"),
    limit: int = Query(200, ge=50, le=200),
    include_ai: bool = Query(False),
    ai_fields: str = Query("rsi,adx,ema_21"),
    request: Request = None
) -> MultiScanResponse:
    ip = (request.client.host if request and request.client else "unknown")

    # Rate limit (Redis אם יש, אחרת זיכרון)
    allowed, _remaining = await rl_allow("scan_multi", ip, limit=int(os.getenv("SCAN_RL_LIMIT", "30")),
                                         window_sec=int(os.getenv("SCAN_RL_WINDOW", "60")))
    if not allowed:
        raise HTTPException(429, "Rate limit exceeded")

    syms_raw = [s.strip().upper() for s in symbols.split(",") if s.strip()]
    if not syms_raw:
        raise HTTPException(400, "No symbols provided")

    if len(syms_raw) > SCAN_MAX_SYMBOLS:
        syms_raw = syms_raw[:SCAN_MAX_SYMBOLS]

    syms = [s if s.endswith("USDT") else s + "USDT" for s in syms_raw]
    want = [f.strip() for f in ai_fields.split(",")] if ai_fields else []

    out: List[ScanSignal] = []

    async def _process(sym: str) -> ScanSignal:
        try:
            df = await _fetch_klines(sym, interval, limit)
            if df.empty:
                return ScanSignal(symbol=sym, interval=interval, ok=False, error="no data")
            ind = await asyncio.to_thread(prepare_indicators_for_backtest, df)
            row = ind.iloc[-1].to_dict()

            ai_txt: Optional[str] = None
            if include_ai:
                slim = {"symbol": sym}
                for k in want:
                    if k in row:
                        slim[k] = row[k]
                try:
                    ai_res = await _maybe_analyze_with_ai(slim)
                    ai_txt = (ai_res or {}).get("analysis")
                except Exception as e:
                    ai_txt = f"AI error: {e}"

            return ScanSignal(symbol=sym, interval=interval,
                              indicators=IndicatorSet(**row), analysis=ai_txt)
        except httpx.HTTPError as he:
            return ScanSignal(symbol=sym, interval=interval, ok=False, error=f"http: {he}")
        except Exception as e:
            logger.warning("scan error %s: %s", sym, e)
            return ScanSignal(symbol=sym, interval=interval, ok=False, error=str(e))

    # להריץ במקביל בצורה מדודה
    sem = asyncio.Semaphore(int(os.getenv("SCAN_CONCURRENCY", "6")))
    async def _guarded(sym: str) -> ScanSignal:
        async with sem:
            return await _process(sym)

    results = await asyncio.gather(*[_guarded(s) for s in syms], return_exceptions=False)
    out.extend(results)

    return MultiScanResponse(ok=True, count_total=len(syms), returned=len(out), signals=out)









































































