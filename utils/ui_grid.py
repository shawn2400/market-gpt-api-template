# routes/ui_grid.py
from __future__ import annotations
import logging
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from typing import List, Dict, Any, Optional

from utils.auth import require_api_key
from utils.grid_manager import get_open_grids, cancel_grid

logger = logging.getLogger("algogpt.routes.ui_grid")

router = APIRouter(prefix="/ui/grid", tags=["Dashboard/Grid"], dependencies=[Depends(require_api_key)])

# ──────────────────────────────────────────────────────────────
# HTML Template
# ──────────────────────────────────────────────────────────────
def _render_dashboard(grids: List[Dict[str, Any]]) -> str:
    rows = ""
    for g in grids:
        sym = g.get("symbol", "?")
        acc_id = g.get("account_id", "main")
        side = g.get("side", "-")
        entry = g.get("entry", 0)
        tp1, tp2, tp3 = (g.get("targets") or [None, None, None])
        sl0 = g.get("sl0", None)

        rows += f"""
        <tr>
            <td>{acc_id}</td>
            <td>{sym}</td>
            <td>{side}</td>
            <td>{entry:.4f}</td>
            <td>{tp1 or '-'}</td>
            <td>{tp2 or '-'}</td>
            <td>{tp3 or '-'}</td>
            <td>{sl0 or '-'}</td>
            <td>
                <form method="post" action="/ui/grid/cancel/{sym}">
                    <input type="hidden" name="account_id" value="{acc_id}"/>
                    <button type="submit">❌ סגור</button>
                </form>
            </td>
        </tr>
        """

    return f"""
    <html>
    <head>
        <title>AlgoGPT Grid Dashboard</title>
        <style>
            body {{ font-family: Arial, sans-serif; margin: 20px; }}
            table {{ border-collapse: collapse; width: 100%; }}
            th, td {{ border: 1px solid #ccc; padding: 6px; text-align: center; }}
            th {{ background-color: #f4f4f4; }}
            h2 {{ color: #333; }}
        </style>
    </head>
    <body>
        <h2>📊 AlgoGPT Grid Dashboard</h2>
        <table>
            <tr>
                <th>Account</th>
                <th>Symbol</th>
                <th>Side</th>
                <th>Entry</th>
                <th>TP1</th>
                <th>TP2</th>
                <th>TP3</th>
                <th>SL</th>
                <th>Actions</th>
            </tr>
            {rows if rows else "<tr><td colspan='9'>אין גרידים פעילים</td></tr>"}
        </table>
    </body>
    </html>
    """

# ──────────────────────────────────────────────────────────────
# Endpoints
# ──────────────────────────────────────────────────────────────
@router.get("/", response_class=HTMLResponse)
async def ui_grid_dashboard() -> HTMLResponse:
    """ טבלת גרידים פעילים """
    grids = get_open_grids()
    html = _render_dashboard(grids)
    return HTMLResponse(content=html)


@router.post("/cancel/{symbol}", response_class=HTMLResponse)
async def ui_grid_cancel(symbol: str, request: Request, account_id: Optional[str] = None):
    """ כפתור סגירת גריד מתוך הדשבורד """
    try:
        form = await request.form()
        acc_id = form.get("account_id") or account_id or "main"
        res = await cancel_grid(symbol, acc_id)
        msg = "✅ גריד נסגר בהצלחה" if res.get("ok") else f"❌ שגיאה: {res}"
        return HTMLResponse(content=f"<h3>{msg}</h3><a href='/ui/grid'>חזרה</a>")
    except Exception as e:
        logger.exception("ui_grid_cancel_failed")
        return HTMLResponse(content=f"<h3>שגיאה: {e}</h3><a href='/ui/grid'>חזרה</a>", status_code=500)



