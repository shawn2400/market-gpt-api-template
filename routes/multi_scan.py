from fastapi import APIRouter, Query, HTTPException
from typing import Tuple
import logging

# ודא שקיימות הפונקציות הבאות:
# - utils.multi_tf_scanner.multi_tf_scan_with_ai(timeframes, markets, min_quality, top, trending_only, trending_source)
from utils.multi_tf_scanner import multi_tf_scan_with_ai

router = APIRouter(
    prefix="/scan",
    tags=["Multi-TF Scanner"],
)

@router.get("/ping")
async def scan_ping():
    return {"ok": True, "endpoint": "/scan/multi"}

@router.get("/multi")
async def scan_multi(
    interval: str = Query("5m,15m,1h", description="טיימפריימים בפסיק, לדוגמה: 5m,15m,1h"),
    min_quality: int = Query(6, ge=1, le=10),
    top: int = Query(10, ge=1),
    market_type: str = Query("futures", description="futures או spot"),
    trending_only: bool = Query(False),
    trending_source: str = Query("coingecko"),
):
    """
    סריקה מרובת טיימפריימים (עם AI אם זמין).
    """
    try:
        tfs: Tuple[str, ...] = tuple([t.strip() for t in interval.split(",") if t.strip()])
        if not tfs:
            raise HTTPException(status_code=422, detail="interval ריק או לא חוקי")

        results = await multi_tf_scan_with_ai(
            timeframes=tfs,
            markets=(market_type,),
            min_quality=min_quality,
            top=top,
            trending_only=trending_only,
            trending_source=trending_source,
        )
        return {
            "ok": True,
            "params": {
                "timeframes": tfs,
                "market_type": market_type,
                "min_quality": min_quality,
                "top": top,
                "trending_only": trending_only,
                "trending_source": trending_source,
            },
            "results": results,
        }
    except HTTPException:
        raise
    except Exception as e:
        logging.exception(f"[scan/multi] error: {e}")
        raise HTTPException(status_code=500, detail=f"scan failed: {e}")
















