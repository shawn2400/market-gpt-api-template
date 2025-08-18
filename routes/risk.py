# routes/risk.py
from __future__ import annotations
from typing import Any, Dict
from fastapi import APIRouter, Depends, HTTPException, Body

try:
    from utils.auth import require_bearer_token
except Exception:
    async def require_bearer_token(*_args, **_kwargs):
        # אם אין מודול auth — נחזיר 401 כדי לא לחשוף בטעות
        raise HTTPException(status_code=401, detail="Unauthorized")

router = APIRouter(prefix="/risk", tags=["Risk"], dependencies=[Depends(require_bearer_token)])

@router.post("/suggest", summary="Suggest budget/leverage/qty from risk engine", operation_id="postRiskSuggest")
async def post_risk_suggest(payload: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
    """
    מעטפת ל-utils.risk.suggest_risk, מחזירה {ok, suggested, inputs, constraints?, note?}
    """
    try:
        from utils.risk import suggest_risk  # הלוגיקה יושבת ב-utils/risk.py
    except Exception:
        raise HTTPException(status_code=500, detail="Risk engine not available")

    try:
        result = suggest_risk(**payload)  # type: ignore
        if not isinstance(result, dict):
            return {"ok": False, "note": "Invalid risk output"}
        result.setdefault("ok", True)
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"risk error: {e}")


  


