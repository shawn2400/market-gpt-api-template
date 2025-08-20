# routes/risk.py
from __future__ import annotations
from typing import Any, Dict
from fastapi import APIRouter, Depends, HTTPException, Body

try:
    from utils.auth import require_bearer_token
except Exception:
    async def require_bearer_token(*_a, **_k):
        raise HTTPException(status_code=401, detail="Unauthorized")

router = APIRouter(tags=["Risk"], dependencies=[Depends(require_bearer_token)])


@router.post("/suggest", summary="Suggest budget/leverage/qty from risk engine", operation_id="postRiskSuggest")
async def post_risk_suggest(payload: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
    """
    ✅ מציע הגדרות Risk (תקציב, מינוף, כמות) לפי אלגוריתם ניהול הסיכונים.
    - payload נדרש להכיל: symbol, balance, entry, sl, tp וכו'.
    - מחזיר: dict עם budget, leverage, qty, risk_score.
    """
    try:
        from utils.risk import suggest_risk
    except Exception:
        raise HTTPException(status_code=500, detail="⚠️ Risk engine not available")

    try:
        res = suggest_risk(**payload)  # type: ignore[arg-type]

        if not isinstance(res, dict):
            return {"ok": False, "error": "Invalid risk output"}

        # החזרת תגובה תקנית
        res.setdefault("ok", True)
        return res

    except HTTPException:
        raise
    except Exception as e:
        # טיפול בשגיאה עסקית
        return {"ok": False, "error": str(e)}






  


