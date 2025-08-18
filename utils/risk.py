# routes/risk.py
from __future__ import annotations
from typing import Any, Dict, Optional
import logging

from fastapi import APIRouter, Depends, HTTPException, Body, status
from pydantic import BaseModel, Field, conint, confloat, validator

logger = logging.getLogger("algogpt.risk")

# ---- Auth (Bearer) ---------------------------------------------------------
try:
    from utils.auth import require_bearer_token  # type: ignore
except Exception:  # pragma: no cover
    def require_bearer_token():
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")

router = APIRouter(prefix="/risk", tags=["Risk"], dependencies=[Depends(require_bearer_token)])

# ---- Schemas (לפי openapi.yaml) -------------------------------------------

class RiskSuggestRequest(BaseModel):
    symbol: str = Field(..., example="BTCUSDT")
    side: str = Field(..., regex="^(LONG|SHORT)$")
    entry: confloat(gt=0)  # required
    sl:    confloat(gt=0)  # required
    tp:    Optional[confloat(gt=0)] = None
    atr:   Optional[confloat(gt=0)] = None
    equity_usdt:     Optional[confloat(gt=0)] = None
    confidence:      Optional[confloat(ge=0, le=100)] = Field(default=None, description="0..100; default 55 if engine uses it")
    max_budget_usdt: Optional[confloat(gt=0)] = None
    max_leverage:    Optional[conint(ge=1, le=125)] = None

    @validator("symbol")
    def _sym(cls, v: str) -> str:
        v = v.strip().upper()
        if not v.endswith("USDT"):
            # לא חוסם – רק נרמול/אזהרה בלוגים
            logger.debug("[/risk/suggest] non-USDT symbol received: %s", v)
        return v

class RiskSuggestResponse(BaseModel):
    ok: bool = True
    suggested: Dict[str, Any]
    inputs: Dict[str, Any]
    constraints: Optional[Dict[str, Any]] = None
    note: Optional[str] = None

# ---- Route -----------------------------------------------------------------

@router.post(
    "/suggest",
    summary="Suggest budget/leverage/qty from risk engine",
    operation_id="postRiskSuggest",
    response_model=RiskSuggestResponse,
)
async def post_risk_suggest(payload: RiskSuggestRequest = Body(...)) -> RiskSuggestResponse:
    """
    מעטפת בטוחה ל-utils.risk.suggest_risk(**kwargs).
    מחזירה מבנה תואם OpenAPI: { ok, suggested, inputs, constraints?, note? }.
    """
    try:
        from utils.risk import suggest_risk  # type: ignore
    except Exception:
        logger.exception("Risk engine not available (utils.risk.suggest_risk missing)")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Risk engine not available")

    try:
        # הפעלה
        result = suggest_risk(**payload.dict())
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("risk error: %s", e)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"risk error: {e}")

    # ולידציה על הפלט
    if not isinstance(result, dict):
        logger.warning("Invalid risk output type: %s", type(result))
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Invalid risk output")

    # נוודא שדות חובה קיימים
    suggested = result.get("suggested")
    inputs    = result.get("inputs")
    if not isinstance(suggested, dict) or not isinstance(inputs, dict):
        logger.warning("Risk output missing required keys: %s", result.keys())
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Malformed risk output")

    # הרכבת תשובה תואמת סכימה
    resp = RiskSuggestResponse(
        ok=bool(result.get("ok", True)),
        suggested=suggested,
        inputs=inputs,
        constraints=result.get("constraints") if isinstance(result.get("constraints"), dict) else None,
        note=result.get("note") if isinstance(result.get("note"), str) else None,
    )
    return resp




