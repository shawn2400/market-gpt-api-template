from __future__ import annotations
from typing import List, Dict, Any
from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse

# Fallbacks לבטיחות פרודקשן
try:
    from utils.auth import require_api_key  # type: ignore
except Exception:
    def require_api_key():
        return None

try:
    from utils.trade_manager import get_trade_history  # type: ignore
except Exception:
    def get_trade_history(limit: int = 200) -> List[Dict[str, Any]]:
        return []

from utils.export_utils import export_trades_csv

router = APIRouter(
    prefix="/export",
    tags=["Export"],
    dependencies=[Depends(require_api_key)]
)

@router.get("/trades.csv", response_class=FileResponse)
def export_trades_csv_route() -> FileResponse:
    trades = get_trade_history(limit=200) or []
    return export_trades_csv(trades)







