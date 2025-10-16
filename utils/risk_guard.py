# utils/risk_guard.py
from __future__ import annotations
import os, logging
from datetime import datetime
from typing import Tuple, Dict, Any

logger = logging.getLogger("algogpt.risk_guard")

# פולבק: אם מודולים לא קיימים – נגדיר פונקציות דמה
try:
    from utils.pnl_summary import get_pnl_summary  # type: ignore
except Exception:
    def get_pnl_summary(limit_days: int = 1) -> Dict[str, Any]:
        return {"days": []}

try:
    from utils.trade_store import list_active  # type: ignore
except Exception:
    def list_active():
        return []


def _get_env_flags() -> Dict[str, Any]:
    return {
        "GLOBAL_OFF": str(os.getenv("GLOBAL_RISK_OFF", "0")).lower() in ("1", "true", "yes", "on"),
        "DAILY_MAX_LOSS": float(os.getenv("DAILY_NET_LOSS_USD_MAX", os.getenv("DAILY_LOSS_CAP_USDT", "999999"))),
        "MAX_OPEN_PER_SYMBOL": int(os.getenv("MAX_CONCURRENT_TRADES_PER_SYMBOL", "999")),
    }


def allow_new_trade(symbol: str) -> Tuple[bool, str]:
    env = _get_env_flags()

    if env["GLOBAL_OFF"]:
        logger.warning("🚫 Trade blocked: GLOBAL_RISK_OFF=1")
        return (False, "GLOBAL_RISK_OFF")

    try:
        sym = (symbol or "").upper()
        cnt = sum(1 for t in list_active() if str(t.get("symbol", "")).upper() == sym)
        if cnt >= env["MAX_OPEN_PER_SYMBOL"]:
            logger.warning("🚫 Trade blocked: MAX_OPEN_PER_SYMBOL reached (%s)", env["MAX_OPEN_PER_SYMBOL"])
            return (False, f"MAX_CONCURRENT_TRADES_PER_SYMBOL={env['MAX_OPEN_PER_SYMBOL']}")
    except Exception as e:
        logger.error("list_active failed: %s", e)

    try:
        day = datetime.utcnow().strftime("%Y-%m-%d")
        pnl = get_pnl_summary(limit_days=1)
        today = next((d for d in pnl.get("days", []) if str(d.get("day")) == day), None)
        loss = float(today.get("pnl", 0.0)) if today else 0.0
        if loss < 0 and abs(loss) > env["DAILY_MAX_LOSS"]:
            logger.warning("🚫 Trade blocked: DAILY_NET_LOSS_USD_MAX=%s hit (loss=%.2f)", env["DAILY_MAX_LOSS"], loss)
            return (False, f"DAILY_NET_LOSS_USD_MAX={env['DAILY_MAX_LOSS']}")
    except Exception as e:
        logger.error("get_pnl_summary failed: %s", e)

    return (True, "OK")


__all__ = ["allow_new_trade"]

