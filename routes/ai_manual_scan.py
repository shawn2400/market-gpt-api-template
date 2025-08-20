# routes/ai_manual_scan.py
from __future__ import annotations
from fastapi import APIRouter, Query
from typing import Dict, Any
import logging

try:
    from utils import analyze
except ImportError:
    analyze = None

router = APIRouter(prefix="/ai", tags=["AI Manual Scan"])

@router.get("/manual-scan", summary="Manual AI Scan for symbol")
async def manual_scan(symbol: str = Query(..., description="e.g. BTCUSDT")) -> Dict[str, Any]:
    try:
        if not analyze:
            return {
                "symbol": symbol,
                "results": {"ok": False, "reason": "analyze module missing"}
            }

        result = analyze.analyze_symbol(symbol)
        return {"symbol": symbol, "results": result}
    except Exception as e:
        logging.exception("manual-scan failed")
        return {"symbol": symbol, "results": {"ok": False, "reason": str(e)}}


        





