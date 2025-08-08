# routes/ai.py
from fastapi import APIRouter, Query, HTTPException
from typing import Any, Dict

from utils.ai_health import ping_openai
from utils.multi_tf_scanner import fallback_scan_manual

router = APIRouter(
    prefix="/ai",
    tags=["AI"]
)

@router.get("/health")
async def ai_health() -> Dict[str, Any]:
    """
    בדיקת בריאות לחיבור OpenAI.
    מחזיר ok/status/פרטים — לא חושף מפתחות.
    """
    res = await ping_openai()
    # אם אין חיבור/הרשאה – עדיין נחזיר 200 עם פירוט, כדי שלא יפיל את /docs
    return res


@router.get("/manual-scan")
async def manual_scan(symbol: str = Query(..., description="סימבול לקריאת ניתוח ידני, למשל BTCUSDT")):
    """
    סריקה ידנית לסימבול יחיד דרך fallback מערכת הסריקה (ללא תלות מלאה ב-GPT).
    """
    try:
        results = await fallback_scan_manual(symbol.upper())
    except HTTPException:
        raise
    except Exception as e:
        # לא לחשוף שגיאות פנימיות — נחזיר 500 עם הודעה נקייה
        raise HTTPException(status_code=500, detail=f"תקלה פנימית בניתוח {symbol}: {e}")

    if not results:
        raise HTTPException(status_code=404, detail=f"לא נמצאו תוצאות עבור {symbol}")

    return {"symbol": symbol.upper(), "results": results}










