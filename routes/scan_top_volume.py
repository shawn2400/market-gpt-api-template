# routes/scan_top_volume.py
from __future__ import annotations
import asyncio
from typing import List, Dict, Any, Optional

from fastapi import APIRouter, Depends, Query, HTTPException, status

# Auth (Bearer) — אם לא קיים, נרשה dev
try:
    from utils.auth import require_bearer_token  # type: ignore
except Exception:
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

async def _build_signal(symbol: str, timeframe: str) -> Dict[str, Any]:
    """
    בנייה מינימלית של סיגנל תקין לפי ה-schema (ללא קריסה גם אם אין סריקה עמוקה).
    אפשר להחליף לניתוח אמיתי אם multi_tf_scanner זמין.
    """
    # נסה ניתוח אמיתי אם יש מודול:
    try:
        from utils.multi_tf_scanner import analyze_symbol  # type: ignore
        res = await analyze_symbol(symbol=symbol, interval=timeframe, market_type="futures", bars=200)
        # צמצום לשדות המוצהרים ב-schema
        return {
            "symbol": symbol,
            "timeframe": timeframe,
            "side": res.get("direction") if res else None,
            "score": float(res.get("quality_score", 0) or 0.0),
            "note": (res.get("reason") or None),
            "details": {
                "rsi": res.get("rsi"),
                "adx": res.get("adx"),
                "atr": res.get("atr"),
                "trend": res.get("trend"),
                "signal": res.get("signal"),
            } if isinstance(res, dict) else None
        }
    except Exception:
        # פולבק קשיח — מחזיר מבנה חוקי ולא שובר את ה־schema
        return {
            "symbol": symbol,
            "timeframe": timeframe,
            "side": None,
            "score": 0.0,
            "note": None,
            "details": None,
        }

@router.get("/top-volume", operation_id="getScanTopVolume")
async def get_scan_top_volume(
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
):
    """
    שלב 1: השג סמלים לפי נפח.
    שלב 2: עבור כל סימבול — ניתוח אמיתי אם קיים מודול, אחרת מבנה מינימלי חוקי.
    """
    ok, symbols = get_top_volume_symbols(market=market, quote=quote, limit=limit)
    if not ok:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Failed to fetch top-volume symbols")

    # ניתוח במקביל — מוגבל בסמפור פנימי של asyncio.gather
    sem = asyncio.Semaphore(concurrency)
    async def _wrap(sym: str):
        async with sem:
            return await _build_signal(sym, timeframe)

    tasks = [asyncio.create_task(_wrap(s)) for s in symbols]
    signals: List[Dict[str, Any]] = await asyncio.gather(*tasks)

    return {"ok": True, "count": len(signals), "signals": signals}

@router_symbols.get("/top-volume", operation_id="getTopVolumeSymbols")
def get_top_volume_symbols_endpoint(
    market: str = Query("futures", pattern="^(futures|spot)$"),
    quote: str = Query("USDT"),
    limit: int = Query(50, ge=1, le=500),
    min_quote_volume: float = Query(0.0, ge=0.0),
):
    ok, symbols = get_top_volume_symbols(
        market=market, quote=quote, limit=limit, min_quote_volume=min_quote_volume
    )
    return {"ok": ok, "market": market, "quote": quote, "limit": limit, "symbols": symbols}











