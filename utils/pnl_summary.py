from __future__ import annotations
from typing import List, Dict, Any

def _as_float(x) -> float:
    try:
        return float(x)
    except Exception:
        return 0.0

def summarize_pnl(trades: List[Dict[str, Any]]) -> Dict[str, Any]:
    total = len(trades or [])
    pnls = [_as_float(t.get("pnl", 0)) for t in (trades or [])]
    total_pnl = sum(pnls)
    wins = sum(1 for v in pnls if v > 0)
    win_rate = (wins / total) if total else 0.0
    avg_pnl = (total_pnl / total) if total else 0.0
    return {
        "total": total,
        "win_rate": round(win_rate * 100, 2),
        "total_pnl": round(total_pnl, 2),
        "avg_pnl": round(avg_pnl, 2),
    }




