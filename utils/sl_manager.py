# utils/sl_manager.py
"""
Zero-Gap Stop Loss Manager.
Ensures positions are never left unprotected when updating SL.
Strategy: place new SL → verify → cancel old SL
"""
from __future__ import annotations
import logging
import time
from typing import Optional, Dict, Any

log = logging.getLogger(__name__)


class ZeroGapSLManager:
    """
    Manages Stop Loss updates with zero-gap protection.
    Never leaves a position without protective stop.
    """

    def __init__(self, binance_client):
        """
        Args:
            binance_client: Module with futures_create_order, futures_cancel_order, get_open_orders
        """
        self.client = binance_client

    def safe_replace_sl(
        self,
        symbol: str,
        new_stop_price: float,
        qty: float,
        side: str,  # "LONG" or "SHORT"
        position_side: Optional[str] = None,
        max_verify_attempts: int = 3,
    ) -> Dict[str, Any]:
        """
        Replace existing SL with new one using zero-gap strategy.

        Steps:
        1. Place new STOP_MARKET order
        2. Verify it's active
        3. Cancel old SL orders
        4. Verify old ones cancelled

        Args:
            symbol: Trading pair (e.g., "BTCUSDT")
            new_stop_price: New stop loss price
            qty: Position quantity (absolute value)
            side: Position side ("LONG" or "SHORT")
            position_side: Hedge mode position side
            max_verify_attempts: Max attempts to verify order placement

        Returns:
            {"success": bool, "new_order_id": int, "cancelled_count": int, "error": str}
        """
        try:
            # Determine order side (opposite of position)
            order_side = "SELL" if side == "LONG" else "BUY"

            # Step 1: Place new SL
            log.info(f"[ZeroGapSL] {symbol} placing new SL @ {new_stop_price} ({side})")
            print(f"[DEBUG SLManager] About to call self.client.futures_create_order, client type: {type(self.client)}")
            print(f"[DEBUG SLManager] positionSide={position_side!r}")
            
            # Build order kwargs, only include positionSide if it's not None
            order_kwargs = {
                "symbol": symbol,
                "side": order_side,
                "type": "STOP_MARKET",
                "quantity": qty,
                "stopPrice": new_stop_price,
                "reduceOnly": True,
                "newClientOrderId": f"SL_{symbol}_{int(time.time())}",
            }
            
            # Only add positionSide if it's explicitly set (not None)
            if position_side is not None:
                order_kwargs["positionSide"] = position_side
            
            new_order = self.client.futures_create_order(**order_kwargs)

            if not new_order or "orderId" not in new_order:
                return {"success": False, "error": "Failed to place new SL", "new_order_id": None, "cancelled_count": 0}

            new_order_id = new_order["orderId"]

            # Step 2: Verify new SL is active
            verified = False
            for attempt in range(max_verify_attempts):
                time.sleep(0.3)  # Brief delay
                open_orders = self.client.get_open_orders(symbol) or []
                for o in open_orders:
                    if o.get("orderId") == new_order_id:
                        status = (o.get("status") or "").upper()
                        if status in ("NEW", "PARTIALLY_FILLED"):
                            verified = True
                            break
                if verified:
                    break
                log.warning(f"[ZeroGapSL] {symbol} verify attempt {attempt + 1}/{max_verify_attempts}")

            if not verified:
                log.error(f"[ZeroGapSL] {symbol} new SL not verified, aborting cancellation")
                return {
                    "success": False,
                    "error": "New SL not verified",
                    "new_order_id": new_order_id,
                    "cancelled_count": 0,
                }

            # Step 3: Cancel old SL orders (exclude the new one)
            log.info(f"[ZeroGapSL] {symbol} new SL verified, cancelling old SLs")
            open_orders = self.client.get_open_orders(symbol) or []
            cancelled_count = 0
            for o in open_orders:
                oid = o.get("orderId")
                if oid == new_order_id:
                    continue  # Don't cancel the new one
                otype = (o.get("type") or "").upper()
                if "STOP" not in otype:
                    continue
                # Check position side match (for Hedge mode)
                if position_side:
                    order_pos_side = (o.get("positionSide") or "").upper()
                    if order_pos_side and order_pos_side != position_side.upper():
                        continue
                try:
                    self.client.futures_cancel_order(symbol, oid)
                    cancelled_count += 1
                    log.info(f"[ZeroGapSL] {symbol} cancelled old SL order {oid}")
                except Exception as e:
                    log.warning(f"[ZeroGapSL] {symbol} failed to cancel {oid}: {e}")

            # Step 4: Verify old orders are gone
            time.sleep(0.2)
            remaining_orders = self.client.get_open_orders(symbol) or []
            remaining_stop_count = 0
            for o in remaining_orders:
                if o.get("orderId") == new_order_id:
                    continue
                otype = (o.get("type") or "").upper()
                if "STOP" in otype:
                    if position_side:
                        order_pos_side = (o.get("positionSide") or "").upper()
                        if order_pos_side == position_side.upper():
                            remaining_stop_count += 1
                    else:
                        remaining_stop_count += 1

            if remaining_stop_count > 0:
                log.warning(f"[ZeroGapSL] {symbol} still has {remaining_stop_count} old SL orders")

            log.info(f"[ZeroGapSL] {symbol} ✅ SL update complete (new: {new_order_id}, cancelled: {cancelled_count})")
            return {
                "success": True,
                "new_order_id": new_order_id,
                "cancelled_count": cancelled_count,
                "error": None,
            }

        except Exception as e:
            log.error(f"[ZeroGapSL] {symbol} error: {e}")
            return {"success": False, "error": str(e), "new_order_id": None, "cancelled_count": 0}
