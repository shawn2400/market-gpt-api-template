# routes/multi_scan.py

from fastapi import APIRouter, Query
from typing import Optional
from utils.scanner_utils import scan_all

router = APIRouter()

@router.get("/scan/multi")
async def scan_multi(
    interval: str = Query("15m", description="טיימפריים לסריקה (למשל 15m, 1h)"),
    min_quality: int = Query(6, ge=1, le=10, description="סף איכות מינימלי"),
    top: int = Query(10, ge=1, description="מספר טריידים שברצונך לקבל"),
    market_type: str = Query("futures", regex="^(futures|spot)$", description="סוג שוק: futures או spot")
):
    """
    סריקה טכנית חיה עם אינדיקטורים וציון איכות. מחזיר את הטריידים הטובים ביותר לפי Quality Score.
    """
    try:
        results = await scan_all(
            interval=interval,
            min_quality=min_quality,
            top=top,
            market_type=market_type
        )
        return {"results": results}
    except Exception as e:
        return {"error": str(e)}












