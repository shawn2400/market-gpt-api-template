# routes/ui_grid.py
from __future__ import annotations
import logging
from fastapi import APIRouter, Depends, Request, Query
from fastapi.responses import HTMLResponse
from typing import List, Dict, Any, Optional

from utils.auth import require_api_key
from utils.grid_manager import _load_state, cancel_grid
from utils.account_router import list_account_ids

logger = logging.getLogger("algogpt.routes.ui_grid")

router = APIRouter(prefix="/ui/grid", tags=["UI-Grid"], dependencies=[])

# ──────────────────────────────────────────────────────────────
# HTML Template
# ──────────────────────────────────────────────────────────────
def _render_dashboard(states: Dict[str, Dict[str, Any]], account_id: Optional[str] = None) -> str:
    rows = []
    for sym, st in states.items():
        if account_id and st.get("account_id") != account_id:
            continue
        rows.append(f"""
        <tr>
            <td>{st.get("account_id","-")}</td>
            <td>{sym}</td>
            <td>{st.get("side")}</td>
            <td>{st.get("entry")}</td>
            <td>{st.get("qty_total")}</td>
            <td>{st.get("sl0")}</td>
            <td>{st.get("targets")}</td>
            <td>
                <form method="post" action="/ui/grid/cancel/{sym}">
                    <input type="hidden" name="account_id" value="{st.get('account_id','main')}"/>
                    <button type="submit">❌ סגור</button>
                </form>
            </td>
        </tr>
        """)
    body = "\n".join(rows) if rows else "<tr><td colspan='8'>אין גרידים פעילים</td></tr>"

    acc_opts = "".join([f"<option value='{a}' {'selected' if a==account_id else ''}>{a}</option>" for a in list_account_ids()])

    return f"""
    <html>
    <head>
        <title>AlgoGPT - Grid Dashboard</title>
        <meta http-equiv="refresh" content="60"> <!-- רענון כל 60 שניות -->
        <style>
            body {{ font-family: Arial, sans-serif; background: #f5f5f5; }}
            table {{ border-collapse: collapse; width: 100%; background: white; }}
            th, td {{ border: 1px solid #ccc; padding: 8px; text-align: center; }}
            th {{ background: #333; color: white; }}
            tr:nth-child(even) {{ background: #f9f9f9; }}
            button {{ background: #e74c3c; color: white; border: none; padding: 6px 12px; cursor: pointer; }}
            button:hover {{ background: #c0392b; }}
            .filter {{ margin-bottom: 15px; }}
        </style>
    </head>
    <body>
        <h2>📊 AlgoGPT Grid Dashboard</h2>
        <div class="filter">
            <form method="get" action="/ui/grid">
                סנן לפי חשבון:
                <select name="account_id">
                    <option value="">הכל</option>
                    {acc_opts}
                </select>
                <button type="submit">סנן</button>
            </form>
        </div>
        <table>
            <thead>
                <tr>
                    <th>חשבון</th>
                    <th>Symbol</th>
                    <th>Side</th>
                    <th>Entry</th>
                    <th>Qty</th>
                    <th>SL</th>
                    <th>Targets</th>
                    <th>ניהול</th>
                </tr>
            </thead>
            <tbody>
                {body}
            </tbody>
        </table>
    </body>
    </html>
    """

# ──────────────────────────────────────────────────────────────
# Routes
# ──────────────────────────────────────────────────────────────
@router.get("", response_class=HTMLResponse)
async def ui_grid_dashboard(request: Request, account_id: Optional[str] = Query(None)):
    """ דשבורד גרידים חי עם פילטר לפי חשבון """
    try:
        # טוען את כל הסטייט מה-grid_manager
        # _load_state הוא פנימי, מחזיר dict פר סימבול
        states: Dict[str, Dict[str, Any]] = {}
        for sym in ["BTCUSDT", "ETHUSDT"]:  # ⚠️ אפשר להרחיב לפי רשימת סינון
            st = _load_state(sym)
            if st:
                states[sym] = st
        html = _render_dashboard(states, account_id)
        return HTMLResponse(content=html)
    except Exception as e:
        logger.exception("ui_grid_dashboard_failed")
        return HTMLResponse(content=f"<h3>שגיאה: {e}</h3>", status_code=500)

@router.post("/cancel/{symbol}", response_class=HTMLResponse)
async def ui_grid_cancel(symbol: str, request: Request, account_id: Optional[str] = None):
    """ כפתור סגירת גריד מתוך הדשבורד """
    try:
        res = await cancel_grid(symbol)
        msg = "✅ גריד נסגר בהצלחה" if res.get("ok") else f"❌ שגיאה: {res}"
        return HTMLResponse(content=f"<h3>{msg}</h3><a href='/ui/grid'>חזרה</a>")
    except Exception as e:
        logger.exception("ui_grid_cancel_failed")
        return HTMLResponse(content=f"<h3>שגיאה: {e}</h3><a href='/ui/grid'>חזרה</a>", status_code=500)


