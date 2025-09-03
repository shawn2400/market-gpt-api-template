# routes/ui_grid.py
from __future__ import annotations
import logging
from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from typing import List

from utils.auth import require_api_key
from utils.account_router import list_account_ids

logger = logging.getLogger("algogpt.routes.ui_grid")

router = APIRouter(
    prefix="/ui/grid",
    tags=["UI-Grid"],
    dependencies=[Depends(require_api_key)],
)

# Templates folder
templates = Jinja2Templates(directory="templates")

@router.get("/", response_class=HTMLResponse)
async def grid_dashboard(request: Request, account_id: str = Query(None)):
    """
    🔹 מציג Dashboard לגרידים + טריידים + PnL.
    אם לא נבחר account_id → מציג את הראשון ברשימה.
    """
    accounts: List[str] = list_account_ids()
    acc_id = account_id or (accounts[0] if accounts else None)

    # ⚠️ כאן אתה יכול למשוך נתוני גרידים/טריידים אמיתיים
    # כרגע נשים דמו כדי שהעמוד יעבוד
    grids = [
        {"symbol": "BTCUSDT", "orders": 3},
        {"symbol": "ETHUSDT", "orders": 2},
    ]
    trades = [
        {"trade_id": "T1", "symbol": "BTCUSDT", "side": "LONG", "entry": 43210, "sl": 42800, "tp": 44500, "pnl": "+120$"},
        {"trade_id": "T2", "symbol": "ETHUSDT", "side": "SHORT", "entry": 3100, "sl": 3180, "tp": 2950, "pnl": "-30$"},
    ]
    pnl_summary = {"realized": 90, "unrealized": 15, "total": 105}

    return templates.TemplateResponse("ui_grid.html", {
        "request": request,
        "accounts": accounts,
        "account_id": acc_id,
        "grids": grids,
        "trades": trades,
        "pnl": pnl_summary,
    })





