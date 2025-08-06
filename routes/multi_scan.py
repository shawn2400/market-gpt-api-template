# routes/multi_scan.py

from fastapi import APIRouter, Query
from typing import Optional
from utils.multi_tf_scanner import multi_tf_scan_with_ai

router = APIRouter()

@router.get("/scan/multi")
async def scan_multi(
    timeframes: Optional[str] = Query("5m,15m,1h"),
    min_quality: int = Query(6, ge=1, le=10),
    top: int = Query(10, ge=1),
    trending_only: Optional[bool] = Query(False),
    trending_source: Optional[str] = Query("binance")
):
    try:
        tfs = tuple(tf.strip() for tf in timeframes.split(","))
        results = await multi_tf_scan_with_ai(
            timeframes=tfs,
            min_quality=min_quality,
            top=top,
            trending_only=trending_only,
            trending_source=trending_source
        )
        return {"results": results}
    except Exception as e:
        return {"error": str(e)}












