# routes/ui_grid.py
from __future__ import annotations
import logging
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse
from typing import Dict, Any, List

from utils.auth import require_api_key
from utils.trade_storage import load_trades  # ✅ שליפת טריידים אמיתיים

router = APIRouter(prefix="/ui/grid", tags=["UI-Grid"], dependencies=[Depends(require_api_key)])
logger = logging.getLogger("algogpt.routes.ui_grid")

@router.get("/", response_class=HTMLResponse)
async def ui_grid_page(request: Request):
    """
    דף HTML של ה-Dashboard
    """
    try:
        from fastapi.templating import Jinja2Templates
        templates = Jinja2Templates(directory="templates")
        return templates.TemplateResponse("ui_grid.html", {"request": request})
    except Exception as e:
        logger.exception("ui_grid_page_failed")
        return HTMLResponse(f"<h1>Error loading UI Grid: {e}</h1>", status_code=500)


@router.get("/data", response_class=JSONResponse)
async def ui_grid_data(account_id: str | None = None) -> Dict[str, Any]:
    """
    🔹 מחזיר JSON של כל הטריידים הפעילים (Grid + רגילים).
    אפשר לסנן לפי account_id.
    """
    try:
        trades: List[dict] = load_trades()  # ✅ טעינה אמיתית
        if account_id:
            trades = [t for t in trades if t.get("account_id") == account_id]

        return {"ok": True, "total": len(trades), "items": trades}
    except Exception as e:
        logger.exception("ui_grid_data_failed")
        return {"ok": False, "error": str(e)}
