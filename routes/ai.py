# routes/ai.py
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from typing import Optional

from utils.auth import require_bearer_token
from utils.scanner_utils import analyze_symbol

router = APIRouter()

class ManualScanItem(BaseModel):
    symbol: str
    market: str
    interval: str
    frames: list[str]
    trend: str
    direction: str
    rsi: float
    adx: float
    volume: float
    quality_score: float
    signal: str
    confidence: int
    reason: str
    close: float
    atr: Optional[float] = None

class AiManualScanResponse(BaseModel):
    symbol: str
    results: ManualScanItem

@router.get(
    "/health",
    tags=["AI"],
    operation_id="getAiHealth",
)
async def ai_health():
    # “דמה” — אפשר לשלב כאן בדיקות מול OpenAI אם תרצה
    return {"ok": True, "model": None, "latency_ms": None, "error": None}

@router.get(
    "/manual-scan",
    tags=["AI"],
    operation_id="getAiManualScan",
    dependencies=[Depends(require_bearer_token)],
    response_model=AiManualScanResponse,
)
async def manual_scan(symbol: str = Query(..., example="BTCUSDT")):
    res = await analyze_symbol(symbol, interval="15m", limit=150)
    if not res:
        raise HTTPException(status_code=404, detail="no data for symbol")
    return {"symbol": symbol.upper(), "results": res}
















