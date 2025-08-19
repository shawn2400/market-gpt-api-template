# routes/scan_top_volume.py
from __future__ import annotations
import asyncio
from typing import List, Dict, Any, Literal, Optional
from fastapi import APIRouter, Depends, Query, HTTPException, status

# ---- Auth (קשיח, לא מפיל את השרת על באג פנימי) ----
try:
    from utils.auth import require_bearer_token as _raw_require_bearer  # type: ignore

    def require_bearer_token():
        # תן ל-HTTPException המקורי לעבור (401 אמיתי), אבל אל תפיל על חריגות אחרות
        try:
            return _raw_require_bearer()
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(status_code=401, detail="Unauthorized")
except Exception:
    # מצב פיתוח / ללא אימות
    def require_bearer_token():
        return None

from utils.top_volume import get_top_volume_symbols

router = APIRouter(
    prefix="/scan",
    tags=["Scan"],
    dependencies=[Depends(require_bearer_token)],
)
router_symbols = APIRouter(
    prefix="/symbols",
    tags=["Analytics"],
    dependencies=[Depends(require_bearer_token)],
)

# ---- Builders ----
async def _signal_lite(symbol: str, timeframe: str) -> Dict[str, Any]:
    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "side": None,
        "score": 0.0,
        "note": None,
        "details": None,
    }

async def _signal_auto(symbol: str, timeframe: str, market: str, bars: int) -> Dict[str, Any]:
    """
    מנסה סורק 'אמיתי' אם קיים; אם אין/נכשל — חוזר ל-lite עם note.
    """
    try:
        # שמור על חתימה מינימלית כדי לא לשבור התקנות שונות
        from utils.multi_tf_scanner import analyze_symbol  # type: ignore
        res = await analyze_symbol(symbol=symbol, interval=timeframe, market_type=market, bars=bars)
        return {
            "symbol": symbol,
            "timeframe": timeframe,
            "side": (res or {}).get("direction"),
            "score": float((res or {}).get("quality_score", 0) or 0.0),
            "note": (res or {}).get("reason"),
            "details": {
                "rsi": (res or {}).get("rsi"),
                "adx": (res or {}).get("adx"),
                "atr": (res or {}).get("atr"),
                "trend": (res or {}).get("trend"),
                "signal": (res or {}).get("signal"),
            } if isinstance(res, dict) else None,
        }
    except Exception as e:
        return {
            "symbol": symbol,
            "timeframe": timeframe,
            "side": None,
            "score": 0.0,
            "note": f"auto-fallback: {type(e).__name__}",
            "details": None,
        }

# ---- /scan/top-volume ----
@router.get("/top-volume", operation_id="getScanTopVolume")
async def get_scan_top_volume(
    market: Literal["futures", "spot"] = Query("futures"),
    quote: str = Query("USDT"),
    limit: int = Query(50, ge=1, le=200),
    timeframe: str = Query("15m"),
    # פרמטרים קיימים ב-openapi — לא מחייב שנשתמש בהם בכל מסלול, אך נשמר תאימות:
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
    mode: Literal["lite", "auto", "deep"] = Query("lite"),
    concurrency: int = Query(16, ge=2, le=64),
):
    """
    mode=lite  → יציב תמיד (אינו תלוי בסורק).
    mode=auto  → מנסה סורק; על כשל/חוסר מודול — חוזר ל-lite (עם note).
    mode=deep  → מחייב מודול סורק; אם חסר — 503 (לא 500).
    """
    ok, symbols = get_top_volume_symbols(market=market, quote=quote, limit=limit)
    if not ok:
        # בעיית קישוריות ל-Binance → 502, לא 500
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Failed to fetch top-volume symbols")

    sem = asyncio.Semaphore(concurrency)

    async def _work(sym: str):
        async with sem:
            if mode == "lite":
                return await _signal_lite(sym, timeframe)
            if mode == "auto":
                return await _signal_auto(sym, timeframe, market, bars)
            # mode == deep → מחייב מודול
            try:
                from utils.multi_tf_scanner import analyze_symbol  # type: ignore
            except Exception:
                raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="deep mode requires scanner")
            res = await analyze_symbol(symbol=sym, interval=timeframe, market_type=market, bars=bars)
            return {
                "symbol": sym,
                "timeframe": timeframe,
                "side": (res or {}).get("direction"),
                "score": float((res or {}).get("quality_score", 0) or 0.0),
                "note": (res or {}).get("reason"),
                "details": res if isinstance(res, dict) else None,
            }

    # לא לתת לחריגה בבודד להפיל 500 — אוספים שגיאות לשדה 'errors'
    results = await asyncio.gather(*(asyncio.create_task(_work(s)) for s in symbols), return_exceptions=True)
    signals: List[Dict[str, Any]] = []
    errors: List[str] = []
    for it in results:
        if isinstance(it, Exception):
            errors.append(f"{type(it).__name__}: {it}")
        else:
            signals.append(it)

    return {
        "ok": True,
        "count": len(signals),
        "signals": signals,
        "errors": errors or None,
        "mode": mode,
        "market": market,
        "quote": quote,
        "timeframe": timeframe,
    }

# ---- /symbols/top-volume (פשוט, ללא תלות בסורק) ----
@router_symbols.get("/top-volume", operation_id="getTopVolumeSymbols")
def get_top_volume_symbols_endpoint(
    market: Literal["futures", "spot"] = Query("futures"),
    quote: str = Query("USDT"),
    limit: int = Query(50, ge=1, le=500),
    min_quote_volume: float = Query(0.0, ge=0.0),
):
    ok, symbols = get_top_volume_symbols(
        market=market,
        quote=quote,
        limit=limit,
        min_quote_volume=min_quote_volume,
    )
    return {"ok": ok, "market": market, "quote": quote, "limit": limit, "symbols": symbols}
















