# routes/ui_grid.py
from __future__ import annotations
import logging
from fastapi import APIRouter, Depends, Query
from fastapi.responses import HTMLResponse
from typing import List, Dict, Any, Optional

from utils.auth import require_api_key
from utils.grid_tracker import get_open_grids

logger = logging.getLogger("algogpt.routes.ui_grid")

router = APIRouter(
    prefix="/ui/grid",
    tags=["UI-Grid"],
    dependencies=[Depends(require_api_key)]
)

@router.get("/json")
def grid_json(account_id: Optional[str] = Query(None, description="סינון לפי account_id")) -> Dict[str, Any]:
    """
    מחזיר JSON עם כל הגרידים הפתוחים.
    אפשר לסנן לפי account_id.
    """
    grids = get_open_grids()
    if account_id:
        grids = [g for g in grids if str(g.get("account_id", "main")) == account_id]
    return {"ok": True, "count": len(grids), "grids": grids}

@router.get("/", response_class=HTMLResponse)
def grid_dashboard() -> str:
    """
    דשבורד HTML בסיסי להצגת גרידים פתוחים.
    כולל בחירת account_id לסינון.
    """
    return """
    <html>
    <head>
        <title>AlgoGPT Grid Dashboard</title>
        <meta charset="utf-8"/>
        <style>
            body { font-family: Arial, sans-serif; margin: 20px; background: #111; color: #eee; }
            h1 { color: #4CAF50; }
            table { border-collapse: collapse; width: 100%; margin-top: 20px; }
            th, td { border: 1px solid #555; padding: 8px; text-align: center; }
            th { background: #333; }
            tr:nth-child(even) { background: #222; }
            button, select { padding: 8px 16px; margin-top: 10px; }
        </style>
    </head>
    <body>
        <h1>🚀 AlgoGPT Grid Dashboard</h1>
        <label for="accountSelect">בחר Account:</label>
        <select id="accountSelect" onchange="loadGrids()">
            <option value="">All</option>
            <option value="main">main</option>
            <option value="spot1">spot1</option>
        </select>
        <button onclick="loadGrids()">רענן עכשיו</button>

        <table id="gridTable">
            <thead>
                <tr>
                    <th>Account</th>
                    <th>Symbol</th>
                    <th>Side</th>
                    <th>Entry</th>
                    <th>Targets</th>
                    <th>SL</th>
                    <th>Created</th>
                </tr>
            </thead>
            <tbody></tbody>
        </table>

        <script>
        async function loadGrids() {
            const acc = document.getElementById("accountSelect").value;
            let url = '/ui/grid/json';
            if (acc) url += '?account_id=' + acc;
            const res = await fetch(url);
            const data = await res.json();
            const tbody = document.querySelector("#gridTable tbody");
            tbody.innerHTML = "";
            if (!data.ok || data.count === 0) {
                tbody.innerHTML = "<tr><td colspan='7'>אין גרידים פתוחים</td></tr>";
                return;
            }
            data.grids.forEach(g => {
                const tr = document.createElement("tr");
                tr.innerHTML = `
                    <td>${g.account_id || "main"}</td>
                    <td>${g.symbol}</td>
                    <td>${g.side}</td>
                    <td>${g.entry || "-"}</td>
                    <td>${(g.targets || []).join("<br/>")}</td>
                    <td>${g.sl0 || "-"}</td>
                    <td>${g.created_at || g.created || "-"}</td>
                `;
                tbody.appendChild(tr);
            });
        }
        // טעינה ראשונית
        loadGrids();
        // רענון כל 60 שניות → לא כבד
        setInterval(loadGrids, 60000);
        </script>
    </body>
    </html>
    """

