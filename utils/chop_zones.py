# utils/chop_zones.py
from __future__ import annotations
import pandas as pd
from typing import List, Tuple

def detect_chop_zones(df: pd.DataFrame, adx_thresh: float = 18.0, min_bars: int = 6) -> List[Tuple[int, int]]:
    if df is None or df.empty or "adx" not in df.columns:
        return []

    in_chop = df["adx"] < adx_thresh
    zones = []
    start = None

    for i, val in enumerate(in_chop):
        if val:
            if start is None:
                start = i
        else:
            if start is not None and (i - start) >= min_bars:
                zones.append((start, i - 1))
            start = None

    if start is not None and (len(df) - start) >= min_bars:
        zones.append((start, len(df) - 1))

    return zones

__all__ = ["detect_chop_zones"]


# utils/chop_viewer.py
from __future__ import annotations
import pandas as pd
from utils.chop_zones import detect_chop_zones

def overlay_chop_zones(df: pd.DataFrame, adx_thresh: float = 18.0, min_bars: int = 6) -> pd.DataFrame:
    df = df.copy()
    df["chop"] = 0
    zones = detect_chop_zones(df, adx_thresh=adx_thresh, min_bars=min_bars)
    for start, end in zones:
        df.loc[start:end, "chop"] = 1
    return df

__all__ = ["overlay_chop_zones"]


# routes/ui.py
from fastapi import APIRouter, Depends, Query
from fastapi.responses import HTMLResponse
from utils.auth import require_api_key
from pathlib import Path

router = APIRouter(
    prefix="/ui",
    tags=["UI"],
    dependencies=[Depends(require_api_key)]
)

@router.get("/dashboard", response_class=HTMLResponse)
def dashboard_page():
    try:
        html_path = Path("static/dashboard/index.html")
        if html_path.exists():
            return html_path.read_text(encoding="utf-8")
    except Exception as e:
        return HTMLResponse(content=f"<h3>Dashboard error</h3><pre>{str(e)}</pre>", status_code=500)
    return HTMLResponse(content="<h3>Dashboard not available</h3>", status_code=404)


# dashboard/app.jsx
import React from 'react';
import { createRoot } from 'react-dom/client';

function App() {
  return (
    <div className="p-4 text-center">
      <h1 className="text-2xl font-bold mb-4">AlgoGPT Dashboard</h1>
      <p className="text-gray-600">Coming soon: Live trade stats, PnL chart, Chop zones viewer</p>
    </div>
  );
}

const root = createRoot(document.getElementById('root'));
root.render(<App />);


// export/daily_report.py
from __future__ import annotations
from typing import List, Dict, Any
import json, datetime
from pathlib import Path

def export_daily_report(trades: List[Dict[str, Any]], dest_dir: str = "static/reports") -> str:
    ts = datetime.datetime.now().strftime("%Y%m%d")
    fname = f"report_{ts}.json"
    Path(dest_dir).mkdir(parents=True, exist_ok=True)
    fpath = Path(dest_dir) / fname
    with open(fpath, "w", encoding="utf-8") as f:
        json.dump(trades, f, indent=2)
    return str(fpath)

__all__ = ["export_daily_report"]

