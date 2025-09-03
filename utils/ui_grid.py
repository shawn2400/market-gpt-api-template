# routes/ui_grid.py
from __future__ import annotations
import logging
from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse
from typing import List, Dict, Any

from utils.auth import require_api_key
from utils.grid_tracker import get_open_grids

logger = logging.getLogger("algogpt.routes.ui_grid")

router = APIRouter(
    prefix="/ui/grid",
    tags=["UI-Grid"],
    dependencies=[Depends(require_api_key)]
)

@router.get("/json")
def grid_json() -> Dict[str, Any]:
    """
    מחזיר JSON עם כל הגרידים הפתוחים.
    זה קליל → רק מידע חיוני מתוך grid_tracker.json.
    """
    grids = get_open_grids()
    return {"ok": True, "count": len(grids), "grids": grids}

@router.get("/", response_class=HTMLResponse)
def grid_dashboard() -> str:
    """
    דשבורד HTML בסיסי → מציג טבלה עם הגרידים הפעילים.
    כולל כפתור רענון (JavaScript) → מושך /ui/grid/json.
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
            button { padding: 8px 16px; margin-top: 10px; }
        </style>
    </head>
    <body>
        <h1>🚀 AlgoGPT Grid Dashboard</h1>
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
            const res = await fetch('/ui/grid/json');
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
