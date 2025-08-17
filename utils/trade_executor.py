# utils/trade_executor.py
import os
from typing import Dict, Any, Optional
from utils.binance_trader import binance_futures_trade

def _bool_env(name: str, default: bool = False) -> bool:
    return str(os.getenv(name, str(default))).lower() in ("1","true","yes","y","on")

async def execute_trade_live(
    symbol: str,
    side: str,
    budget: float,
    leverage: int,
    entry: float,
    sl: Optional[float] = None,
    tp: Optional[float] = None,
    dry_run: bool = True,
) -> Dict[str, Any]:
    if dry_run or _bool_env("BINANCE_SKIP_ACCOUNT_MUTATIONS", True) or not _bool_env("EXECUTE_TRADES", False):
        # מצב יבש – מחזיר תכנית פעולה
        return {
            "mode": "dry_run",
            "symbol": symbol.upper(),
            "side": side.upper(),
            "entry": float(entry),
            "sl": float(sl) if sl else None,
            "tp": float(tp) if tp else None,
            "leverage": int(leverage),
            "budget": float(budget),
        }
    if sl is None or tp is None:
        raise ValueError("SL/TP must be provided for live execution")
    return await binance_futures_trade(
        symbol=symbol, side=side, entry=entry, sl=sl, tp=tp, leverage=leverage, budget=budget
    )






















































