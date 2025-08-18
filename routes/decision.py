# routes/decision.py
from __future__ import annotations
from typing import Any, Dict
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

try:
    from utils.auth import require_bearer_token  # type: ignore
except Exception:
    def require_bearer_token():
        raise HTTPException(status_code=401, detail="Unauthorized")

try:
    from utils.scoring import decision_score  # type: ignore
except Exception:
    def decision_score(_: Dict[str, Any]) -> float:
        return 0.0

router = APIRouter(prefix="/decision", tags=["Decision"], dependencies=[Depends(require_bearer_token)])

class DecisionIn(BaseModel):
    components: Dict[str, Any] = {}

class DecisionOut(BaseModel):
    score: float

@router.post("/", response_model=DecisionOut, operation_id="postDecisionScore_v2140")
async def post_decision(payload: DecisionIn) -> DecisionOut:
    return DecisionOut(score=decision_score(payload.components or {}))



