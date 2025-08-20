# routes/ai_manual_scan.py
from __future__ import annotations
import logging
from typing import Dict, Any, Optional

from fastapi import APIRouter, Query
from utils import analyze   # ✅ מודול חדש שנטען בהצלחה
from utils.indicators import prepare_indicators_for_backtest

logger = logging.getLogger("ai_manual_scan")

router = APIRouter(prefix="/ai", tags=["AI Manual Scan"])

@router.get("/manual-scan")
async def manual_scan(
    symbol: str = Query(..., description="Trading pair, e.g. BTCUSDT"),
    interval: str = Query("15m", description="Kline interval, default=15m"),
    limit: int = Query(200, ge=50, le=1500),
) -> Dict[str, Any]:
    """
    Manual scan endpoint — מחזיר ניתוח טכני בסיסי.
    """
    try:
        df = analyze.fetch_klines(symbol, interval, limit)
        if df.empty:
            return {"symbol": symbol, "results": {"ok": False, "reason": "no data"}}

        ind = prepare_indicators_for_backtest(df)
        if ind.empty:
            return {"symbol": symbol, "results": {"ok": False, "reason": "no indicators"}}

        row: Dict[str, Any] = ind.iloc[-1].to_dict()

        # ניקוי ערכים לסוגי float/bool פשוטים
        results: Dict[str, Any] = {
            k: (float(v) if isinstance(v, (int, float)) else (bool(v) if isinstance(v, (bool,)) else v))
            for k, v in row.items()
        }
        results.update({
            "symbol": symbol,
            "interval": interval,
            "ok": True,
        })

        return {"symbol": symbol, "results": results}

    except Exception as e:
        logger.exception("manual_scan failed")
        return {
            "symbol": symbol,
            "results": {"ok": False, "reason": f"analyze-fallback: {type(e).__name__}", "error": str(e)},
        }





