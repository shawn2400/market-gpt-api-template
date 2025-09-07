# utils/risk_guard.py
from __future__ import annotations
import os
from datetime import datetime
from typing import Tuple
from utils.pnl_summary import get_pnl_summary
from utils.trade_store import list_active

_GLOBAL_OFF = str(os.getenv("GLOBAL_RISK_OFF", "0")).lower() in ("1", "true", "yes", "on")
_DAILY_MAX_LOSS = float(os.getenv("DAILY_NET_LOSS_USD_MAX", "999999"))
_MAX_OPEN_PER_SYMBOL = int(os.getenv("MAX_CONCURRENT_TRADES_PER_SYMBOL", "999"))

def allow_new_trade(symbol: str) -> Tuple[bool, str]:
    """
    שומר על כללי ניהול סיכונים בסיסיים:
    - אם GLOBAL_RISK_OFF פעיל → אין טריידים
    - לא לעבור על MAX_CONCURRENT_TRADES_PER_SYMBOL
    - לא לעבור על DAILY_NET_LOSS_USD_MAX
    """
    if _GLOBAL_OFF:
        return (False, "GLOBAL_RISK_OFF")

    sym = (symbol or "").upper()
    cnt = sum(1 for t in list_active() if str(t.get("symbol", "")).upper() == sym)
    if cnt >= _MAX_OPEN_PER_SYMBOL:
        return (False, f"MAX_CONCURRENT_TRADES_PER_SYMBOL={_MAX_OPEN_PER_SYMBOL}")

    day = datetime.utcnow().strftime("%Y-%m-%d")
    pnl = get_pnl_summary(limit_days=1)
    today = next((d for d in pnl.get("days", []) if d.get("day") == day), None)
    loss = float(today.get("pnl", 0.0)) if today else 0.0

    if loss < 0 and abs(loss) > _DAILY_MAX_LOSS:
        return (False, f"DAILY_NET_LOSS_USD_MAX={_DAILY_MAX_LOSS}")

    return (True, "OK")

