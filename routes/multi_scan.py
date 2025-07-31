# routes/multi_scan.py

from fastapi import APIRouter, Query
from utils.multi_tf_scanner import multi_tf_scan_with_ai

router = APIRouter()

@router.get("/scan/multi")
async def scan_multi(
    timeframes: str = Query("5m,15m,1h,4h", description="טיימפריימים מופרדים בפסיק"),
    min_quality: int = Query(6),
    top: int = Query(10),
    trending_only: bool = Query(False),
    trending_source: str = Query("binance", description="מקור טרנדינג: binance / lunarcrush / coingecko"),
):
    """
    סריקה חכמה לפי כמה טיימפריימים, כולל ניתוח AI.
    """
    tf_list = [t.strip() for t in timeframes.split(",")]
    trades = await multi_tf_scan_with_ai(
        timeframes=tf_list,
        min_quality=min_quality,
        top=top,
        trending_only=trending_only,
        trending_source=trending_source
    )
    return {"trades": trades}



