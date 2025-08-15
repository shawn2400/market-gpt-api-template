# routes/multi_scan.py
from fastapi import APIRouter, Query, Depends
from typing import Optional
from utils.auth import require_bearer_token
from utils.multi_tf_scanner import multi_tf_scan_with_ai, fallback_scan_manual

router = APIRouter(prefix="/scan", tags=["Multi-TF Scanner"], dependencies=[Depends(require_bearer_token)])

@router.get("/multi")
async def scan_multi(
    interval: Optional[str] = Query("5m,15m,1h", description="רשימת טיימפריימים מופרדים בפסיקים"),
    min_quality: int = Query(6, ge=1, le=10, description="ציון איכות מינימלי (0–10)"),
    top: int = Query(10, ge=1, description="מספר הטריידים המובילים"),
    market_type: Optional[str] = Query("futures", description="סוג שוק: futures או spot"),
    trending_only: Optional[bool] = Query(False, description="האם לסנן רק מטבעות טרנדיים"),
    trending_source: Optional[str] = Query("coingecko", description="מקור למטבעות טרנדיים")
):
    try:
        timeframes = tuple(interval.split(","))
        results = await multi_tf_scan_with_ai(
            timeframes=timeframes,
            markets=(market_type,),
            min_quality=min_quality,
            top=top,
            trending_only=trending_only,
            trending_source=trending_source
        )
        if not results:
            return {"warning": "לא נמצאו טריידים איכותיים, הופעל fallback ידני",
                    "results": await fallback_scan_manual("BTCUSDT")}
        return {"results": results}
    except Exception as e:
        return {"error": str(e), "results": await fallback_scan_manual("BTCUSDT")}




































