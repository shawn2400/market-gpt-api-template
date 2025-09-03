# routes/ui_grid.py
from __future__ import annotations
import logging
from fastapi import APIRouter, Depends, Query, Request, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from typing import List, Dict, Any

from utils.auth import require_api_key
from utils.account_router import list_account_ids
from utils.grid_manager import list_active_grids
from utils.trade_storage import load_open_trades
from utils.pnl_summary import get_pnl_summary

logger = logging.getLogger("algogpt.routes.ui_grid")

router = APIRouter(
    prefix="/ui/grid",
    tags=["UI-Grid"],
    dependencies=[Depends(require_api_key)],
)

# תיקיית טמפלטים
templates = Jinja2Templates(directory="templates")

@router.get("/", response_class=HTMLResponse)
async def grid_dashboard(request: Request, account_id: str = Query(None)):
    """
    🔹 Dashboard אמיתי לגרידים / טריידים / PnL
    - account_id: סינון לפי חשבון (או הראשון ברשימה)
    - גרידים: נשלף מ-grid_manager
    - טריידים: נשלף מ-trade_storage
    - PnL: נשלף מ-pnl_summary
    """
    accounts: List[str] = list_account_ids()
    if not accounts:
        raise HTTPException(status_code=400, detail="No accounts configured")
    acc_id = account_id or accounts[0]

    # --- גרידים פעילים ---
    try:
        grids: List[Dict[str, Any]] = list_active_grids(account_id=acc_id)
    except Exception as e:
        logger.exception("failed_to_load_grids")
        grids = []

    # --- טריידים פתוחים ---
    try:
        trades: List[Dict[str, Any]] = load_open_trades(account_id=acc_id)
    except Exception as e:
        logger.exception("failed_to_load_trades")
        trades = []

    # --- PnL Summary ---
    try:
        pnl = get_pnl_summary(account_id=acc_id)
    except Exception as e:
        logger.exception("failed_to_load_pnl")
        pnl = {"realized": 0, "unrealized": 0, "total": 0}

    return templates.TemplateResponse("ui_grid.html", {
        "request": request,
        "accounts": accounts,
        "account_id": acc_id,
        "grids": grids,
        "trades": trades,
        "pnl": pnl,
    })





