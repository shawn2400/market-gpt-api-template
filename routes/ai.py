from fastapi import APIRouter, Query, HTTPException
from typing import Any, Dict

from utils.ai_health import ping_openai
from utils.multi_tf_scanner import fallback_scan_manual

router = APIRouter(prefix="/ai", tags=["AI"])

@router.get("/health")
async def ai_health() -> Dict[str, Any]:
    # מחזיר ok/status או פירוט שגיאה; לא מפיל את /docs
    return await ping_openai()

@router.get("/manual-scan")
async def manual_scan(symbol: str = Query(..., description="סימבול כמו BTCUSDT")):
    try:
        results = await fallback_scan_manual(symbol.upper())
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"תקלה פנימית בניתוח {symbol}: {e}")

    if not results:
        raise HTTPException(status_code=404, detail=f"לא נמצאו תוצאות עבור {symbol}")

    return {"symbol": symbol.upper(), "results": results}












