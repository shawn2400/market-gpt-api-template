# -*- coding: utf-8 -*-
from __future__ import annotations
from typing import Literal

def should_time_stop(entry_time_ms: int, now_ms: int, min_minutes: int) -> bool:
    return (now_ms - entry_time_ms) >= (min_minutes * 60_000)

def time_stop_decision(side_txt: str, entry_price: float, price_now: float,
                       profit_lock_min_pct: float = 0.0) -> Literal["MOVE_BE","KEEP"]:
    # if in profit above threshold -> move BE, else keep
    try:
        pnl_pct = (price_now / entry_price - 1.0) * (1 if side_txt.upper()=="LONG" else -1)
        return "MOVE_BE" if pnl_pct >= profit_lock_min_pct/100.0 else "KEEP"
    except Exception:
        return "KEEP"
