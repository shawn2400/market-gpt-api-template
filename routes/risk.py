# routes/risk.py
from __future__ import annotations
from typing import Any, Dict
from fastapi import APIRouter, Depends, HTTPException, Body

try:
    from utils.auth import require_bearer_token
except Exception:
    async def require_bearer_token(*_a, **_k):
        raise HTTPException(status_code=401, detail="Unauthorized")

from utils.risk import suggest_risk

router = APIRouter(tags=["Risk"], dependencies=[Depends(require_bearer_token)])


@router.post("/suggest", summary="Suggest budget/leverage/qty from risk engine", operation_id="postRiskSuggest")
async def post_risk_suggest(payload: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
    """
    ✅ מציע הגדרות Risk (תקציב, מינוף, כמות) לפי אלגוריתם ניהול הסיכונים.
    - payload נדרש להכיל: symbol, entry, sl (+ balance/equtiy_usdt אופציונלי).
    """
    try:
        res = suggest_risk(**payload)  # type: ignore[arg-type]

        if not isinstance(res, dict):
            return {"ok": False, "error": "Invalid risk output"}

        return res
    except HTTPException:
        raise
    except Exception as e:
        return {"ok": False, "error": str(e)}







  


