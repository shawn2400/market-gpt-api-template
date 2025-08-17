import os
from typing import Any, Dict, Optional

from utils.binance_trader import binance_futures_trade

EXECUTE_TRADES = str(os.getenv("EXECUTE_TRADES", "false")).lower() in ("1", "true", "yes", "on")

async def execute_trade_live(
    *,
    symbol: str,
    side: str,
    budget: float,
    leverage: int,
    entry: float,
    sl: float,
    tp: float,
    dry_run: bool = True,
    quantity: Optional[float] = None,
) -> Dict[str, Any]:
    if dry_run or not EXECUTE_TRADES:
        return {
            "mode": "dry_run",
            "symbol": symbol.upper(),
            "side": side.upper(),
            "entry": float(entry),
            "sl": float(sl),
            "tp": float(tp),
            "leverage": int(leverage),
            "budget": float(budget),
            "quantity": quantity,
        }
    # LIVE (Binance)
    return await binance_futures_trade(
        symbol=symbol,
        side=side,
        entry=entry,
        sl=sl,
        tp=tp,
        leverage=leverage,
        budget=budget,
        quantity=quantity,
        market_type="futures",
    )






















































