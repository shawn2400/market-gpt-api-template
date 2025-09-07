# routes/risk.py
from __future__ import annotations
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Body, Header, Request
from utils.risk import suggest_risk

# הגנה בסיסית (Bearer), ובנוסף HMAC אופציונלי
try:
    from utils.auth import require_bearer_token
except Exception:
    async def require_bearer_token(*_a, **_k):
        raise HTTPException(status_code=401, detail="Unauthorized")

from utils.security import verify_hmac

import os
WEBHOOK_HMAC_SECRET = os.getenv("WEBHOOK_HMAC_SECRET", "").strip()

router = APIRouter(prefix="/risk", tags=["Risk"], dependencies=[Depends(require_bearer_token)])

@router.post("/suggest", summary="Suggest budget/leverage/qty from risk engine", operation_id="postRiskSuggest")
async def post_risk_suggest(
    request: Request,
    payload: Dict[str, Any] = Body(...),
    x_signature: Optional[str] = Header(None)
) -> Dict[str, Any]:
    """
    ✅ מציע הגדרות Risk (תקציב, מינוף, כמות) לפי אלגוריתם ניהול הסיכונים.
    דרוש: symbol, entry, sl (אופציונלי: balance/equity_usdt, budget_usd, leverage).
    """
    if WEBHOOK_HMAC_SECRET:
        raw = await request.body()
        if not verify_hmac(x_signature, raw):
            raise HTTPException(status_code=401, detail="Invalid HMAC signature")
    try:
        res = suggest_risk(**payload)  # type: ignore[arg-type]
        if not isinstance(res, dict):
            return {"ok": False, "error": "Invalid risk output"}
        res.setdefault("ok", True)
        return res
    except HTTPException:
        raise
    except Exception as e:
        return {"ok": False, "error": str(e)}

# תאימות ל־ENV הקיים: RISK_QUICK_URL=/risk/quick
@router.post("/quick", summary="Alias to /risk/suggest")
async def post_risk_quick(
    request: Request,
    payload: Dict[str, Any] = Body(...),
    x_signature: Optional[str] = Header(None)
) -> Dict[str, Any]:
    if WEBHOOK_HMAC_SECRET:
        raw = await request.body()
        if not verify_hmac(x_signature, raw):
            raise HTTPException(status_code=401, detail="Invalid HMAC signature")
    try:
        res = suggest_risk(**payload)  # type: ignore[arg-type]
        if not isinstance(res, dict):
            return {"ok": False, "error": "Invalid risk output"}
        res.setdefault("ok", True)
        return res
    except HTTPException:
        raise
    except Exception as e:
        return {"ok": False, "error": str(e)}








  


