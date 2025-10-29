from __future__ import annotations
from typing import List, Dict, Optional, Any, Protocol

class _TradeProto(Protocol):
    realized_pnl: float
    def to_dict(self) -> Dict[str, Any]: ...

def _pnl_of(t: Any) -> float:
    # תמיכה ב־Trade או Dict
    if hasattr(t, "realized_pnl"):
        v = getattr(t, "realized_pnl")
        try:
            return float(v)
        except Exception:
            return 0.0
    if isinstance(t, dict):
        try:
            return float(t.get("realized_pnl", t.get("pnl", 0.0)) or 0.0)
        except Exception:
            return 0.0
    return 0.0

def calculate_total_pnl(trades: List[Any]) -> float:
    return sum(_pnl_of(t) for t in (trades or []))

def calculate_win_rate(trades: List[Any]) -> float:
    pnls = [_pnl_of(t) for t in (trades or [])]
    wins = sum(1 for p in pnls if p > 0)
    total = len(pnls)
    return round(100.0 * wins / total, 2) if total > 0 else 0.0

def calculate_avg_pnl(trades: List[Any]) -> float:
    pnls = [_pnl_of(t) for t in (trades or [])]
    return round(sum(pnls) / len(pnls), 2) if pnls else 0.0

def calculate_summary(trades: List[Any]) -> Dict[str, float]:
    return {
        "total_pnl": calculate_total_pnl(trades),
        "win_rate_pct": calculate_win_rate(trades),
        "avg_pnl": calculate_avg_pnl(trades),
        "num_trades": len(trades or []),
    }



