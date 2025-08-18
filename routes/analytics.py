# routes/analytics.py
from __future__ import annotations
import asyncio
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Query

router = APIRouter(prefix="/analytics", tags=["Analytics"])

@router.get("/macro", summary="Macro snapshot (DXY/NDX/SPX/FG/BTC.D)", operation_id="getMacro")
async def get_macro() -> Dict[str, Any]:
    """
    תמיד מחזיר 200.
    אם ספק המאקרו לא קונפיגורד – מחזיר ערכים ריקים + note (לא Unauthorized).
    """
    try:
        from utils.macro import get_macro_snapshot  # type: ignore
    except Exception:
        get_macro_snapshot = None  # type: ignore

    if get_macro_snapshot:
        try:
            if getattr(get_macro_snapshot, "__await__", None):
                data = await get_macro_snapshot()  # type: ignore
            else:
                data = await asyncio.to_thread(get_macro_snapshot)  # type: ignore
            if isinstance(data, dict) and data:
                data.setdefault("ok", True)
                return data
        except Exception:
            pass

    return {
        "ok": True,
        "dxy": None,
        "ndx": None,
        "spx": None,
        "btc_dominance": None,
        "fear_greed": None,
        "updated_at": None,
        "note": "Macro provider not configured – set API keys or utils.macro",
    }

@router.get("/correlation", summary="Correlation ALT to BTC", operation_id="getCorrelation")
async def get_correlation(
    symbols: List[str] = Query(..., description="CSV or repeated, e.g. ETHUSDT,SOLUSDT"),
    ref_symbol: str = Query("BTCUSDT"),
    timeframe: str = Query("15m"),
    window: int = Query(200),
) -> Dict[str, Any]:
    """
    אם utils.correlation קיים – נשתמש בו; אחרת נחזיר שלדים עם corr=None.
    """
    try:
        from utils.correlation import compute_correlation  # type: ignore
    except Exception:
        compute_correlation = None  # type: ignore

    if compute_correlation:
        try:
            items = await asyncio.to_thread(compute_correlation, symbols, ref_symbol, timeframe, window)  # type: ignore
            return {"ok": True, "items": items or []}
        except Exception:
            pass

    return {
        "ok": True,
        "items": [
            {"symbol": s, "ref_symbol": ref_symbol, "window": window,
             "corr_close": None, "beta": None, "lead_lag_bars": None, "note": "correlation provider not configured"}
            for s in symbols
        ],
    }

@router.get("/sentiment/summary", summary="Sentiment summary (-100..100)", operation_id="getSentiment")
async def get_sentiment() -> Dict[str, Any]:
    """
    אם utils.sentiment קיים – נחזיר ערך אמיתי; אחרת fallback ניטרלי (200).
    """
    try:
        from utils.sentiment import get_sentiment_summary  # type: ignore
    except Exception:
        get_sentiment_summary = None  # type: ignore

    if get_sentiment_summary:
        try:
            data = await asyncio.to_thread(get_sentiment_summary)  # type: ignore
            if isinstance(data, dict) and data:
                data.setdefault("ok", True)
                return data
        except Exception:
            pass

    return {"ok": True, "score": 0.0, "buckets": {}, "samples": 0}

