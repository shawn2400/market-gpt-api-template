# utils/export_utils.py
import csv, json
from typing import List, Dict, Any
from datetime import datetime


def export_trades_to_csv(trades: List[Dict[str, Any]], file_path: str) -> None:
    if not trades:
        return
    keys = trades[0].keys()
    with open(file_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=keys)
        writer.writeheader()
        writer.writerows(trades)


def export_trades_to_json(trades: List[Dict[str, Any]], file_path: str) -> None:
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(trades, f, indent=2, ensure_ascii=False)


def generate_daily_filename(prefix: str = "trades") -> str:
    now = datetime.utcnow().strftime("%Y%m%d")
    return f"{prefix}_{now}.csv"


# utils/pnl_summary.py
from typing import List, Dict, Any

def compute_pnl_summary(trades: List[Dict[str, Any]]) -> Dict[str, Any]:
    realized_total = 0.0
    win = 0
    loss = 0
    for t in trades:
        pnl = float(t.get("realized_pnl", 0.0))
        realized_total += pnl
        if pnl > 0:
            win += 1
        elif pnl < 0:
            loss += 1

    total = len(trades)
    win_rate = (win / total) * 100 if total > 0 else 0.0
    avg_pnl = realized_total / total if total > 0 else 0.0

    return {
        "total_trades": total,
        "realized_total": realized_total,
        "win_rate": win_rate,
        "avg_pnl": avg_pnl,
        "wins": win,
        "losses": loss,
    }

