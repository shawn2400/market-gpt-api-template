# export/daily_report.py
from __future__ import annotations
import os, json
from datetime import datetime
from utils.pnl_summary import summarize_trades
from utils.trade_state import Trade
from typing import List

EXPORT_DIR = "static/reports"
os.makedirs(EXPORT_DIR, exist_ok=True)

def export_daily_report(trades: List[Trade]) -> str:
    """
    שומר קובץ JSON עם היסטוריית טריידים + סיכום יומי.
    """
    now = datetime.utcnow().strftime("%Y%m%d_%H%M")
    fname = f"daily_report_{now}.json"
    path = os.path.join(EXPORT_DIR, fname)

    summary = summarize_trades(trades)
    payload = {
        "generated_at": now,
        "summary": summary,
        "trades": [t.to_dict() for t in trades],
    }

    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    return path

