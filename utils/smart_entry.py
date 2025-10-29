# utils/smart_entry.py
# -*- coding: utf-8 -*-
from __future__ import annotations
from typing import Dict, Any

def plan_hybrid_entry(*, symbol: str, side: str, notional_usdt: float,
                      mark_price: float, spread_bps: float,
                      max_slip_bps: float = 5.0) -> Dict[str, Any]:
    side = side.upper()
    if spread_bps <= 2.0:
        return {
            "mode": "market+limit",
            "legs": [
                {"type":"MARKET", "fraction":0.40},
                {"type":"LIMIT",  "fraction":0.60,
                 "px_offset_bps": (-max_slip_bps if side=="BUY" else +max_slip_bps)}
            ]
        }
    else:
        return {
            "mode": "limit_then_market",
            "legs": [
                {"type":"LIMIT",  "fraction":1.00,
                 "px_offset_bps": (-max_slip_bps if side=="BUY" else +max_slip_bps),
                 "cancel_after_sec":20},
                {"type":"MARKET", "fraction":0.25, "if_unfilled_after_sec":20}
            ]
        }
