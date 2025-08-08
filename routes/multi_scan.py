# routes/multi_scan.py
from fastapi import APIRouter, Query
from typing import Optional
from utils.multi_tf_scanner import multi_tf_scan_with_ai
from utils.watchlist_utils import load_watchlist

router = APIRouter(
    prefix="/scan",
    tags=["Multi-TF Scanner"]
)

@router.get("/multi")
async def scan_multi(
    interval: Optional[str] = Query("5m,15m,1h", description="רשימת טיימפריימים מופרדים בפסיקים"),
    min_quality: int = Query(6, ge=1, le=10, description="ציון איכות מינימלי (0–10)"),
    top: int = Query(10, ge=1, description="מספר הטריידים המובילים"),
    market_type: Optional[str] = Query("futures", description="סוג שוק: futures או spot"),
    trending_only: Optional[bool] = Query(False, description="האם לסנן רק מטבעות טרנדיים"),
    trending_source: Optional[str] = Query("coingecko", description="מקור למטבעות טרנדיים")
):
    """
    סריקת שוק לפי מספר טיימפריימים + AI, עם עדיפות ל־watchlist.json אם קיים.
    """
    # טעינת רשימת המעקב
    watchlist_symbols = load_watchlist(min_quality=min_quality)
    if watchlist_symbols:
        trending_only = False  # אם יש watchlist, לא נכריח טרנדינג בלבד

    timeframes = tuple(interval.split(","))

    results = await multi_tf_scan_with_ai(
        timeframes=timeframes,
        markets=(market_type,),
        min_quality=min_quality,
        top=top,
        trending_only=trending_only,
        trending_source=trending_source
    )

    return {"count": len(results), "results": results}
















