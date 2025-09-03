# utils/book_gates.py
from __future__ import annotations
from typing import Optional, Dict, Any

def spread_bps(best_bid: Optional[float], best_ask: Optional[float]) -> Optional[float]:
    try:
        b = float(best_bid); a = float(best_ask)
        if b <= 0 or a <= 0:
            return None
        if a <= b:
            return 0.0
        mid = (a + b) / 2.0
        return abs(a - b) / mid * 10000.0
    except Exception:
        return None

def gate_spread_depth(
    *, best_bid: Optional[float], best_ask: Optional[float],
    bid_qty: Optional[float] = None, ask_qty: Optional[float] = None,
    max_spread_bps: float = 3.0, min_top_qty: float = 0.0
) -> Dict[str, Any]:
    sp = spread_bps(best_bid, best_ask)
    if sp is None:
        return {"ok": False, "code": "spread_na", "details": {"spread_bps": None}}
    if sp > max_spread_bps:
        return {"ok": False, "code": "spread_high", "details": {"spread_bps": sp, "max": max_spread_bps}}
    if min_top_qty and (bid_qty is not None) and (ask_qty is not None):
        if bid_qty < min_top_qty or ask_qty < min_top_qty:
            return {"ok": False, "code": "depth_low", "details": {"bid_qty": bid_qty, "ask_qty": ask_qty, "min_top_qty": min_top_qty}}
    return {"ok": True, "code": "ok", "details": {"spread_bps": sp}}

def gate_mark_index_sanity(*, mark: Optional[float], index: Optional[float], max_gap_bps: float = 20.0) -> Dict[str, Any]:
    try:
        m = float(mark); i = float(index)
        if m <= 0 or i <= 0:
            return {"ok": False, "code": "mark_or_index_na", "details": {"mark": mark, "index": index}}
        gap_bps = abs(m - i) / i * 10000.0
        if gap_bps > max_gap_bps:
            return {"ok": False, "code": "mark_index_gap", "details": {"gap_bps": gap_bps, "max": max_gap_bps}}
        return {"ok": True, "code": "ok", "details": {"gap_bps": gap_bps}}
    except Exception:
        return {"ok": False, "code": "mark_or_index_na", "details": {"mark": mark, "index": index}}

def gate_pump_nuke(delta5m_abs_pct: Optional[float], *, threshold_pct: float = 1.0) -> Dict[str, Any]:
    if delta5m_abs_pct is None:
        return {"ok": True, "code": "no_signal"}
    return {
        "ok": delta5m_abs_pct <= threshold_pct,
        "code": "pump_nuke" if delta5m_abs_pct > threshold_pct else "ok",
        "details": {"abs_5m_pct": delta5m_abs_pct, "max": threshold_pct},
    }

def gate_volume_ratio(ratio_ma20: Optional[float], *, min_ratio: float = 1.2) -> Dict[str, Any]:
    if ratio_ma20 is None:
        return {"ok": True, "code": "no_signal"}
    return {
        "ok": ratio_ma20 >= min_ratio,
        "code": "low_volume" if ratio_ma20 < min_ratio else "ok",
        "details": {"ratio_ma20": ratio_ma20, "min": min_ratio},
    }

__all__ = [
    "spread_bps", "gate_spread_depth", "gate_mark_index_sanity",
    "gate_pump_nuke", "gate_volume_ratio",
]


