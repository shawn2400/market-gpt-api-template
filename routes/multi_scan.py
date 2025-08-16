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
    trending_source: Optional[str] = Query("coingecko", description="מקור למטבעות טרנדיים"),
    hard_btc_filter: Optional[bool] = Query(False, description="סינון קשיח לפי מגמת BTC (עשוי להחזיר ריק)"),
    allow_divergence: Optional[bool] = Query(False, description="להתיר הצגת מועמדים נגד BTC (preview בלבד)")
):
    """
    סריקה רכה (Soft) כברירת מחדל. ניתן להפעיל hard_btc_filter לסינון קשיח.
    התגובה כוללת Hard Preview לכל מועמד: btc_dir/aligned/hard_status/executable/fast_reply/leverage_suggest.
    """
    try:
        timeframes = tuple([s.strip() for s in (interval or "").split(",") if s.strip()])
        results = await multi_tf_scan_with_ai(
            timeframes=timeframes or ("5m", "15m", "1h"),
            markets=(market_type,),
            min_quality=min_quality,
            top=top,
            trending_only=trending_only,
            trending_source=trending_source,
            hard_btc_filter=bool(hard_btc_filter),
            allow_divergence=bool(allow_divergence),
        )
        if not results:
            return {
                "warning": "לא נמצאו טריידים איכותיים, הופעל fallback ידני",
                "results": await fallback_scan_manual("BTCUSDT")
            }
        return {"results": results}
    except Exception as e:
        return {"error": str(e), "results": await fallback_scan_manual("BTCUSDT")}







































