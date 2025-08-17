from fastapi import APIRouter, Depends, HTTPException, Query
from utils.auth import require_bearer_token
from utils.metrics import metrics_tracker
from utils.scanner_utils import analyze_symbol

router = APIRouter()

@router.get(
    "/health",
    tags=["AI"],
    operation_id="getAiHealth",
    summary="AI health (OpenAI)",
)
async def ai_health():
    # בדיקת זמינות כללית פשוטה (ללא קריאה ל-OpenAI בפועל)
    return {"ok": True, "model": None, "latency_ms": None, "error": None}

@router.get(
    "/manual-scan",
    tags=["AI"],
    operation_id="getAiManualScan",
    summary="Manual scan (per symbol)",
)
async def ai_manual_scan(
    symbol: str = Query(..., min_length=3, max_length=20),
    _: None = Depends(require_bearer_token),
):
    try:
        item = await analyze_symbol(symbol, market_type="futures", interval="15m", limit=150)
        if not item:
            raise HTTPException(status_code=404, detail="No data")
        return {"symbol": symbol.upper(), "results": item}
    except HTTPException:
        raise
    except Exception as e:
        metrics_tracker.record_error()
        raise HTTPException(status_code=500, detail=str(e))















