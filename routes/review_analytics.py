# routes/review_analytics.py
from __future__ import annotations
from fastapi import APIRouter, Query
from utils.review_analytics import compute_analytics

router = APIRouter(prefix="", tags=["analytics"])

@router.get("/review/analytics")
async def review_analytics(days: int = Query(7, ge=1, le=90)):
    """
    אנליטיקות בסיסיות:
    - יחס BE→SL
    - יחס TP1→TP2
    - זמן ממוצע בפוזיציה (דקות)
    המקור: TRADES_LOG_PATH (JSON Lines)
    """
    return {"ok": True, "analytics": compute_analytics(days)}
