# routes/multi_scan.py

from fastapi import APIRouter
from utils.multi_tf_scanner import multi_tf_scan_with_ai

router = APIRouter()

@router.get("/scan/multi", tags=["Scan"])
async def multi_tf_scan_api(
    min_quality: int = 6,
    top: int = 10,
    frames: str = "5m,15m,1h",
    markets: str = "futures,spot",
    trending_only: bool = False,
    trending_source: str = "coingecko"  # ✅ קריטי – נדרש לשם הפונקציה
):
    timeframes = [f.strip() for f in frames.split(",")]
    market_list = [m.strip() for m in markets.split(",")]

    results = await multi_tf_scan_with_ai(
        timeframes=timeframes,
        markets=market_list,
        min_quality=min_quality,
        top=top,
        trending_only=trending_only,
        trending_source=trending_source
    )
    return {
        "count": len(results),
        "results": results
    }



