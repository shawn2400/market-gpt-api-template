# routes/ai_manual_scan.py
from __future__ import annotations
from fastapi import APIRouter, Query
from typing import Dict, Any

from utils.analyze import analyze_symbol

router = APIRouter(prefix="/ai", tags=["AI"])

@router.get("/manual-scan", summary="Manual AI Scan for symbol")
async def manual_scan(symbol: str = Query(..., description="e.g. BTCUSDT")) -> Dict[str, Any]:
    try:
        result = analyze_symbol(symbol, interval="15m")
        return {"symbol": symbol, "results": result}
    except Exception as e:
        return {"symbol": symbol, "ok": False, "error": str(e)}

        





