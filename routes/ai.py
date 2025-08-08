from fastapi import APIRouter, Query, HTTPException
from utils.multi_tf_scanner import fallback_scan_manual

router = APIRouter(
    prefix="/ai",
    tags=["AI"]
)

@router.get("/manual-scan")
async def manual_scan(symbol: str = Query(..., description="סימבול לקריאת ניתוח ידני")):
    results = await fallback_scan_manual(symbol.upper())
    if not results:
        raise HTTPException(status_code=404, detail=f"לא נמצאו תוצאות עבור {symbol}")
    return {"results": results}










