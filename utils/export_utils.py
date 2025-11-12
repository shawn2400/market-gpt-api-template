import csv, os, json
from fastapi.responses import FileResponse
from pathlib import Path
from typing import List, Dict, Any

EXPORT_DIR = Path("static/exports")
EXPORT_DIR.mkdir(parents=True, exist_ok=True)

def _stable_fieldnames(rows: List[Dict[str, Any]]) -> List[str]:
    if not rows:
        return []
    # מאחד את כל המפתחות כדי לשמור יציבות בין רשומות עם שדות שונים
    keys = []
    seen = set()
    for r in rows:
        for k in r.keys():
            if k not in seen:
                seen.add(k)
                keys.append(k)
    return keys

def export_trades_csv(trades: List[Dict[str, Any]]) -> FileResponse:
    fname = EXPORT_DIR / "trades_export.csv"
    fieldnames = _stable_fieldnames(trades) or ["symbol","side","pnl","ts"]
    with open(fname, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for t in trades or []:
            writer.writerow({k: t.get(k) for k in fieldnames})
    return FileResponse(fname, filename="trades_export.csv")

def export_daily_csv(date: str = None) -> str:
    """Export daily GRID trades to CSV."""
    import datetime
    if not date:
        date = datetime.datetime.now().strftime("%Y-%m-%d")
    fname = EXPORT_DIR / f"grid_daily_{date}.csv"
    # Placeholder - implement actual GRID data export
    with open(fname, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["symbol", "side", "entry", "exit", "pnl", "timestamp"])
    return str(fname)

def export_daily_pdf(date: str = None) -> str:
    """Export daily GRID trades to PDF."""
    import datetime
    if not date:
        date = datetime.datetime.now().strftime("%Y-%m-%d")
    fname = EXPORT_DIR / f"grid_daily_{date}.pdf"
    # Placeholder - implement actual PDF generation
    with open(fname, "w") as f:
        f.write(f"GRID Daily Report - {date}\n")
    return str(fname)




