# routes/ai.py
from __future__ import annotations

import os
from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Depends, Query
from pydantic import BaseModel

from utils.auth import require_bearer_token
from utils.scanner_utils import analyze_symbol

router = APIRouter(prefix="/ai", tags=["AI"])

@router.get("/health", operation_id="getAiHealth")
async def ai_health() -> Dict[str, Any]:
    """
    בדיקת זמינות OpenAI: אם יש OPENAI_API_KEY נחזיר ok=true; אחרת ok=false + error.
    (ללא קריאה חיצונית כדי למנוע כשלי רשת/חסימות בזמן deploy)
    """
    api_key = os.getenv("OPENAI_API_KEY")
    return {"ok": bool(api_key), "model": None, "latency_ms": None, "error": None if api_key else "OPENAI_API_KEY not set"}

@router.get(
    "/manual-scan",
    operation_id="getAiManualScan",
    dependencies=[Depends(require_bearer_token)],
)
async def manual_scan(symbol: str = Query(..., description="סימבול כמו BTCUSDT")):
    """
    ניתוח סימבול בודד (RSI/ADX/EMA/ATR) ומדד איכות. משתמש ב-Binance Futures klines.
    """
    res = await analyze_symbol(symbol.upper())
    if not res:
        raise HTTPException(status_code=404, detail=f"לא נמצאו נתונים ל-{symbol}")
    return {"symbol": symbol.upper(), "results": res}














