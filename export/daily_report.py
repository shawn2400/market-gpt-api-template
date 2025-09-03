# export/daily_report.py
from __future__ import annotations
import pandas as pd
from utils.pnl_summary import summarize_trades
from utils.export_utils import save_json
from datetime import datetime
from typing import List, Dict, Any
from pathlib import Path

def generate_daily_report(trades: List[Dict[str, Any]], out_dir: str | Path = "static/reports") -> str:
    df = summarize_trades(trades)
    if df.empty:
        raise ValueError("No trades to report")

    date_str = datetime.utcnow().strftime("%Y-%m-%d")
    report_path = Path(out_dir) / f"report_{date_str}.json"
    save_json(df.to_dict(orient="records"), report_path)
    return str(report_path)


