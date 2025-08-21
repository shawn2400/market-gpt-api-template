# routes/strategy.py
from __future__ import annotations
import os
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from utils.auth import require_bearer_token

router = APIRouter(tags=["Strategy"], dependencies=[Depends(require_bearer_token)])

class StrategyVersion(BaseModel):
    ok: bool
    algogpt_version: str
    strategy_version: str
    git_commit: str | None

@router.get("/version", response_model=StrategyVersion, summary="Get strategy version")
async def get_strategy_version() -> StrategyVersion:
    return StrategyVersion(
        ok=True,
        algogpt_version=os.getenv("ALGOGPT_VERSION", "unknown"),
        strategy_version=os.getenv("STRATEGY_VERSION", "unknown"),
        git_commit=os.getenv("GIT_COMMIT"),
    )

