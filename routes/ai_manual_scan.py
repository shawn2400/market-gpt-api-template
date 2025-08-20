from __future__ import annotations
from fastapi import APIRouter, Query
from utils import analyze

router = APIRouter(prefix="/ai", tags=["AI Manual Scan"])

@router.get("/manual-scan")
async def manual_scan(symbol: str = Query(..., description="Symbol, e.g. BTCUSDT")):
    results = analyze.analyze_symbol(symbol)
    return {"symbol": symbol, "results": results}




