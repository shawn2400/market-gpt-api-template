# ✅ trade_executor.py - גרסה סופית ותקינה עם תמיכה ב־quantity
from __future__ import annotations
import logging, uuid
from typing import Dict, Any, Optional
from utils.binance_client import (
    futures_create_order,
    futures_mark_price,
    set_leverage,
    get_symbol_info,
)

logger = logging.getLogger("algogpt.trade_executor")

def _round_qty(symbol: str, qty: float) -> float:
    try:
        info = get_symbol_info(symbol)
        if not info:
            return round(qty, 6)
        step = float(info.get("filters", [{}])[2].get("stepSize", 0.001))
        min_q = float(info.get("filters", [{}])[2].get("minQty", 0.0))
        qty = max(qty, min_q)
        return (qty // step) * step
    except Exception:
        return round(qty, 6)

async def execute_trade_live(
    *,
    symbol: str,
    side: str,
    budget: float,
    leverage: int = 10,
    entry: Optional[float] = None,
    sl: Optional[float] = None,
    tp: Optional[float] = None,
    dry_run: bool = False,
    quantity: Optional[float] = None,
    position_side: str = "BOTH",
    reduce_only: bool = False,
) -> Dict[str, Any]:
    try:
        mark = futures_mark_price(symbol)
        if not mark:
            return {"ok": False, "error": f"mark_price_unavailable for {symbol}"}

        price_ref = entry or mark
        qty = quantity if quantity is not None else (budget * leverage) / price_ref
        qty = _round_qty(symbol, qty)
        if qty <= 0:
            return {"ok": False, "error": "qty_invalid"}

        if dry_run:
            return {
                "ok": True,
                "symbol": symbol,
                "side": side.upper(),
                "qty": qty,
                "price": price_ref,
                "entry": None,
                "sl": sl,
                "tp": tp,
                "dry_run": True,
            }

        set_leverage(symbol, leverage)
        client_oid = f"ALGOGPT-{uuid.uuid4().hex[:12]}"

        entry_order = futures_create_order(
            symbol=symbol,
            side=side.upper(),
            type="MARKET",
            quantity=str(qty),
            reduceOnly=reduce_only,
            positionSide=position_side,
            newClientOrderId=client_oid,
        )
        if not entry_order.get("orderId"):
            return {"ok": False, "error": entry_order}

        result = {
            "ok": True,
            "symbol": symbol,
            "side": side.upper(),
            "qty": qty,
            "price": mark,
            "entry": entry_order,
            "sl": None,
            "tp": None,
        }

        hedge_side = "SELL" if side.upper() in ("BUY", "LONG") else "BUY"

        if sl:
            result["sl"] = futures_create_order(
                symbol=symbol,
                side=hedge_side,
                type="STOP_MARKET",
                stopPrice=str(sl),
                quantity=str(qty),
                reduceOnly=True,
                timeInForce="GTC",
                positionSide=position_side,
                newClientOrderId=f"{client_oid}-SL",
            )
        if tp:
            result["tp"] = futures_create_order(
                symbol=symbol,
                side=hedge_side,
                type="TAKE_PROFIT_MARKET",
                stopPrice=str(tp),
                quantity=str(qty),
                reduceOnly=True,
                timeInForce="GTC",
                positionSide=position_side,
                newClientOrderId=f"{client_oid}-TP",
            )

        logger.info("[trade_executor] executed: %s", result)
        return result

    except Exception as e:
        logger.exception("[trade_executor] execution error: %s", e)
        return {"ok": False, "error": str(e)}

__all__ = ["execute_trade_live"]































































