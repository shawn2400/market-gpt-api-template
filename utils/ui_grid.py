# routes/ui_grid.py
from __future__ import annotations
import logging
from fastapi import APIRouter, Depends, Query, HTTPException
from typing import Dict, Any, List, Optional

from utils.auth import require_api_key
from utils.account_router import list_account_ids
from utils.grid_manager import list_active_grids  # נניח שקיים (או אפשר להרחיב)
from utils.trade_storage import load_trades        # טבלה של כל הטריידים
from utils.pnl_tracker import get_pnl_summary      # רווח/הפסד מצטבר

logger = logging.getLogger("algogpt.routes.ui_grid")

router = APIRouter(
    prefix="/ui/grid",
    tags=["UI-Grid"],
    dependencies=[Depends(require_api_key)],
)

# ──────────────────────────────────────────────
# Endpoints
# ──────────────────────────────────────────────

@router.get("/accounts")
def ui_list_accounts() -> Dict[str, Any]:
    """
    מחזיר את רשימת ה־account_id הנתמכים (מה־accounts_config.json).
    """
    return {"ok": True, "accounts": list_account_ids()}


@router.get("/active")
def ui_active_grids(account_id: Optional[str] = Query(None, description="סינון לפי account_id")) -> Dict[str, Any]:
    """
    מציג גרידים פעילים, עם אפשרות לסינון לפי חשבון.
    """
    try:
        grids = list_active_grids()  # אמור להחזיר [{"symbol":..,"account_id":..,"orders":[..]}]
        if account_id:
            grids = [g for g in grids if g.get("account_id") == account_id]
        return {"ok": True, "active": grids}
    except Exception as e:
        logger.exception("ui_active_grids_failed")
        raise HTTPException(status_code=500, detail=f"Failed to fetch grids: {e}")


@router.get("/trades")
def ui_trades(account_id: Optional[str] = Query(None)) -> Dict[str, Any]:
    """
    מציג את כל הטריידים מה־trade_storage.json, עם אפשרות סינון לפי חשבון.
    """
    try:
        trades = load_trades()
        if account_id:
            trades = [t for t in trades if t.get("account_id") == account_id]
        return {"ok": True, "trades": trades}
    except Exception as e:
        logger.exception("ui_trades_failed")
        raise HTTPException(status_code=500, detail=f"Failed to fetch trades: {e}")


@router.get("/pnl")
def ui_pnl(account_id: Optional[str] = Query(None)) -> Dict[str, Any]:
    """
    מציג PnL מצטבר. אם account_id → יציג רק את הטריידים של אותו חשבון.
    """
    try:
        summary = get_pnl_summary(account_id=account_id)
        return {"ok": True, "summary": summary}
    except Exception as e:
        logger.exception("ui_pnl_failed")
        raise HTTPException(status_code=500, detail=f"Failed to fetch PnL: {e}")




