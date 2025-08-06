# routes/multi_scan.py

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse
import logging
from utils.multi_tf_scanner import multi_tf_scan_with_ai

router = APIRouter()

@router.get("/scan/multi")
async def scan_multi(
    timeframes: str = Query("5m,15m,1h", description="טיימפריימים מופרדים בפסיק"),
    min_quality: int = Query(6, ge=0, le=10, description="ציון איכות מינימלי (0–10)"),
    top: int = Query(10, ge=1, le=50, description="מספר מקסימלי של טריידים להחזרה"),
    trending_only: bool = Query(False, description="האם לסנן לפי סימבולים טרנדיים בלבד"),
    trending_source: str = Query("binance", description="מקור טרנדינג: binance / lunarcrush / coingecko"),
):
    try:
        tf_list = [t.strip() for t in timeframes.split(",") if t.strip()]
        if not tf_list:
            return JSONResponse(
                status_code=400,
                content={"status": "error", "message": "אין טיימפריימים חוקיים לסריקה."}
            )

        trades = await multi_tf_scan_with_ai(
            timeframes=tf_list,
            min_quality=min_quality,
            top=top,
            trending_only=trending_only,
            trending_source=trending_source
        )

        return {
            "status": "success",
            "count": len(trades),
            "trades": trades
        }

    except Exception as e:
        logging.exception("[multi_scan] ❌ שגיאה כללית בסריקה")
        return JSONResponse(
            status_code=500,
            content={"status": "error", "message": str(e)}
        )








