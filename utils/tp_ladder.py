# utils/tp_ladder.py
"""
Dynamic Take Profit Ladder Manager.
Places TP1-TP4 with configurable weights (50%/30%/20%).
"""
from __future__ import annotations
import logging
import os
from typing import Dict, Any, List, Optional

log = logging.getLogger(__name__)


class TPLadder:
    """Manages multi-level Take Profit orders."""

    def __init__(self, binance_client):
        """
        Args:
            binance_client: Module with futures_create_order, futures_cancel_order, get_open_orders
        """
        self.client = binance_client

        # Default TP ladder weights (must sum to ~1.0)
        self.tp1_pct = float(os.getenv("TP_LADDER_TP1_PCT", "0.50"))
        self.tp2_pct = float(os.getenv("TP_LADDER_TP2_PCT", "0.30"))
        self.tp3_pct = float(os.getenv("TP_LADDER_TP3_PCT", "0.20"))

    def set_tp_ladder(
        self,
        symbol: str,
        entry_price: float,
        qty: float,
        side: str,  # "LONG" or "SHORT"
        tp_prices: List[float],  # [TP1, TP2, TP3, TP4] (can be 2-4 levels)
        position_side: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Place multi-level TP orders with weighted quantities.

        Args:
            symbol: Trading pair
            entry_price: Position entry price
            qty: Total position quantity
            side: Position side ("LONG" or "SHORT")
            tp_prices: List of TP prices [TP1, TP2, TP3, TP4]
            position_side: Hedge mode position side

        Returns:
            {"success": bool, "placed_orders": List[int], "error": str}
        """
        try:
            if not tp_prices or len(tp_prices) < 2:
                return {"success": False, "error": "Need at least 2 TP levels", "placed_orders": []}

            # Determine order side (opposite of position)
            order_side = "SELL" if side == "LONG" else "BUY"

            # Cancel existing TP orders first
            self._cancel_existing_tps(symbol, position_side)

            # Calculate quantities for each TP level
            total_assigned = 0.0
            tp_quantities = []

            if len(tp_prices) >= 3:
                # 3 or 4 levels: 50%, 30%, 20%
                tp_quantities = [
                    qty * self.tp1_pct,
                    qty * self.tp2_pct,
                    qty * self.tp3_pct,
                ]
                # Remainder goes to TP4 if exists
                if len(tp_prices) == 4:
                    remainder = qty - sum(tp_quantities)
                    tp_quantities.append(max(0, remainder))
            else:
                # 2 levels: 60%, 40%
                tp_quantities = [qty * 0.60, qty * 0.40]

            # Ensure we don't exceed total qty
            tp_quantities = tp_quantities[: len(tp_prices)]
            total_assigned = sum(tp_quantities)
            if total_assigned > qty:
                # Normalize
                scale = qty / total_assigned
                tp_quantities = [q * scale for q in tp_quantities]

            # Place TP orders
            placed_orders = []
            for i, (tp_price, tp_qty) in enumerate(zip(tp_prices, tp_quantities)):
                if tp_qty <= 0:
                    continue

                # Round qty to step size
                tp_qty_str, tp_qty_float = self._normalize_qty(symbol, tp_qty)
                if tp_qty_float <= 0:
                    log.warning(f"[TPLadder] {symbol} TP{i + 1} qty too small after rounding")
                    continue

                # Round price to tick size
                tp_price_str, tp_price_float = self._normalize_price(symbol, tp_price)

                try:
                    # Build order kwargs
                    order_kwargs = {
                        "symbol": symbol,
                        "side": order_side,
                        "type": "LIMIT",
                        "quantity": tp_qty_str,
                        "price": tp_price_str,
                        "timeInForce": "GTC",
                        "newClientOrderId": f"TP{i + 1}_{symbol}_{int(tp_price_float)}",
                    }
                    
                    # Add positionSide if set, otherwise add reduceOnly
                    # Note: Binance API doesn't accept both positionSide and reduceOnly together
                    if position_side is not None:
                        order_kwargs["positionSide"] = position_side
                    else:
                        order_kwargs["reduceOnly"] = True
                    
                    order = self.client.futures_create_order(**order_kwargs)
                    if order and "orderId" in order:
                        placed_orders.append(order["orderId"])
                        log.info(
                            f"[TPLadder] {symbol} placed TP{i + 1} @ {tp_price_float} qty={tp_qty_float} (order {order['orderId']})"
                        )
                except Exception as e:
                    log.error(f"[TPLadder] {symbol} failed to place TP{i + 1}: {e}")

            if not placed_orders:
                return {"success": False, "error": "No TP orders placed", "placed_orders": []}

            log.info(f"[TPLadder] {symbol} ✅ TP ladder complete ({len(placed_orders)} orders)")
            return {"success": True, "placed_orders": placed_orders, "error": None}

        except Exception as e:
            log.error(f"[TPLadder] {symbol} error: {e}")
            return {"success": False, "error": str(e), "placed_orders": []}

    def _cancel_existing_tps(self, symbol: str, position_side: Optional[str] = None) -> int:
        """Cancel existing TP (LIMIT) orders for this symbol."""
        try:
            orders = self.client.get_open_orders(symbol) or []
            cancelled = 0
            for o in orders:
                otype = (o.get("type") or "").upper()
                if otype != "LIMIT":
                    continue
                reduce_only = o.get("reduceOnly", False)
                if not reduce_only:
                    continue
                # Check position side match
                if position_side:
                    order_pos_side = (o.get("positionSide") or "").upper()
                    if order_pos_side and order_pos_side != position_side.upper():
                        continue
                oid = o.get("orderId")
                if oid:
                    try:
                        self.client.futures_cancel_order(symbol, oid)
                        cancelled += 1
                    except Exception:
                        pass
            if cancelled > 0:
                log.info(f"[TPLadder] {symbol} cancelled {cancelled} existing TP orders")
            return cancelled
        except Exception as e:
            log.warning(f"[TPLadder] {symbol} error cancelling TPs: {e}")
            return 0

    def _normalize_price(self, symbol: str, price: float) -> tuple[str, float]:
        """Round price to tick size."""
        try:
            from utils.binance_client import get_symbol_filters

            filters = get_symbol_filters(symbol) or {}
            tick = float(filters.get("tickSize", 0.01))
            if tick <= 0:
                tick = 0.01
            steps = round(price / tick)
            normalized = steps * tick
            # Calculate decimals
            if "." in str(tick):
                dec_count = len(str(tick).split(".")[1].rstrip("0"))
            else:
                dec_count = 0
            formatted = f"{normalized:.{dec_count}f}"
            return formatted, float(formatted)
        except Exception:
            return f"{price:.8f}", price

    def _normalize_qty(self, symbol: str, qty: float) -> tuple[str, float]:
        """Round qty to step size."""
        try:
            from utils.binance_client import get_symbol_filters
            import math

            filters = get_symbol_filters(symbol) or {}
            step = float(filters.get("stepSize", 0.001))
            if step <= 0:
                step = 0.001
            steps = math.floor(max(0.0, qty) / step)
            normalized = max(step, steps * step)
            # Calculate decimals
            if "." in str(step):
                dec_count = len(str(step).split(".")[1].rstrip("0"))
            else:
                dec_count = 0
            formatted = f"{normalized:.{dec_count}f}"
            return formatted, float(formatted)
        except Exception:
            return f"{qty:.8f}", qty
