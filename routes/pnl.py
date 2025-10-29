from __future__ import annotations
from typing import Dict, Any, List
from fastapi import APIRouter, Depends
from pydantic import BaseModel

# Fallbacks
try:
    from utils.auth import require_api_key  # type: ignore
except Exception:
    def require_api_key():
        return None

try:
    from utils.trade_manager import get_trade_history  # type: ignore
except Exception:
    def get_trade_history(limit: int = 500) -> List[Dict[str, Any]]:
        return []

from utils.pnl_summary import summarize_pnl

router = APIRouter(
    prefix="/pnl",
    tags=["PnL"],
    dependencies=[Depends(require_api_key)]
)

class PnLSummaryResponse(BaseModel):
    ok: bool = True
    summary: Dict[str, Any]

@router.get("/summary", response_model=PnLSummaryResponse)
def pnl_summary() -> PnLSummaryResponse:
    trades = get_trade_history(limit=500) or []
    summary = summarize_pnl(trades)
    return PnLSummaryResponse(ok=True, summary=summary)





