from __future__ import annotations
import datetime, json, os
from pathlib import Path
from typing import List, Dict, Any

def _to_dict(t: Any) -> Dict[str, Any]:
    if hasattr(t, "to_dict"):
        try:
            return t.to_dict()  # type: ignore
        except Exception:
            pass
    if isinstance(t, dict):
        return t
    # best-effort
    return {"repr": repr(t)}

def generate_daily_report(trades: List[Any]) -> Dict[str, Any]:
    today = datetime.date.today().isoformat()
    # חישוב סיכום
    try:
        from utils.pnl_calculator import calculate_summary  # late import
        summary = calculate_summary(trades)
    except Exception:
        summary = {}
    return {
        "date": today,
        "summary": summary,
        "trades": [_to_dict(t) for t in (trades or [])],
    }

def save_report_to_file(report: Dict[str, Any], path: str) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)



