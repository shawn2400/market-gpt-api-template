# routes/ui_grid.py
from __future__ import annotations
import logging
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse
from typing import Dict, Any
from utils.auth import require_api_key

router = APIRouter(prefix="/ui/grid", tags=["UI-Grid"], dependencies=[Depends(require_api_key)])
logger = logging.getLogger("algogpt.routes.ui_grid")

# כאן אפשר בעתיד לחבר ל-trade_storage או grid_manager כדי להביא נתונים אמיתיים
_FAKE_ACTIVE_GRIDS: list[dict] = []


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
    🔹 מחזיר JSON של כל הגרידים הפעילים.
    אפשר לסנן לפי account_id.
    """
    try:
        items = list(_FAKE_ACTIVE_GRIDS)  # כאן בעתיד נקשר ל-trade_storage או DB

        if account_id:
            items = [g for g in items if g.get("account_id") == account_id]

        return {"ok": True, "total": len(items), "items": items}
    except Exception as e:
        logger.exception("ui_grid_data_failed")
        return {"ok": False, "error": str(e)}
