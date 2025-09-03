# utils/pnl_calculator.py
from __future__ import annotations
from typing import List, Dict, Optional
from utils.trade_state import Trade

def calculate_total_pnl(trades: List[Trade]) -> float:
    return sum(t.realized_pnl for t in trades if isinstance(t.realized_pnl, (int, float)))

def calculate_win_rate(trades: List[Trade]) -> float:
    wins = sum(1 for t in trades if t.realized_pnl > 0)
    total = len(trades)
    return round(100.0 * wins / total, 2) if total > 0 else 0.0

def calculate_avg_pnl(trades: List[Trade]) -> float:
    if not trades:
        return 0.0
    return round(sum(t.realized_pnl for t in trades) / len(trades), 2)

def calculate_summary(trades: List[Trade]) -> Dict[str, float]:
    return {
        "total_pnl": calculate_total_pnl(trades),
        "win_rate_pct": calculate_win_rate(trades),
        "avg_pnl": calculate_avg_pnl(trades),
        "num_trades": len(trades),
    }


# export/daily_report.py
from __future__ import annotations
import datetime, json
from typing import List, Dict, Any
from utils.pnl_calculator import calculate_summary
from utils.trade_state import Trade


def generate_daily_report(trades: List[Trade]) -> Dict[str, Any]:
    today = datetime.date.today().isoformat()
    summary = calculate_summary(trades)
    
    return {
        "date": today,
        "summary": summary,
        "trades": [t.to_dict() for t in trades],
    }

def save_report_to_file(report: Dict[str, Any], path: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

