#!/usr/bin/env python3
# utils/order_consolidation_engine.py
"""
Order Consolidation Engine - Permanent Fix for Binance 10 Stop Order Limit

Instead of CANCEL-CREATE cycle (which hits the limit), this engine:
1. Finds existing TP orders for a symbol
2. Updates their prices WITHOUT creating new orders
3. Falls back to create only if NO existing orders exist

This beats the 10-order-per-symbol limit by reusing order slots.
"""
import logging
from typing import Dict, List, Optional, Any

logger = logging.getLogger("order_consolidation")


class OrderConsolidationEngine:
    """
    Manages order consolidation to avoid Binance's 10-stop-order-per-symbol limit.
    """
    
    def __init__(self):
        self.logger = logger
    
    def find_existing_tp_orders(self, all_orders: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Find existing TP orders from all orders list.
        
        Args:
            all_orders: List of all orders from Binance
            
        Returns:
            List of existing TP orders (TAKE_PROFIT, TAKE_PROFIT_MARKET, or LIMIT reduceOnly)
        """
        tp_orders = []
        
        for order in all_orders:
            # Match TP order types
            order_type = order.get("type", "").upper()
            is_reduce_only = order.get("reduceOnly", False)
            
            # TP orders are either explicit TP type or LIMIT with reduceOnly=True
            if order_type in ("TAKE_PROFIT", "TAKE_PROFIT_MARKET"):
                tp_orders.append(order)
            elif order_type == "LIMIT" and is_reduce_only:
                # LIMIT with reduceOnly is a TP equivalent
                tp_orders.append(order)
        
        return sorted(tp_orders, key=lambda x: float(x.get("stopPrice", 0)))
    
    def can_update_order(self, order: Dict[str, Any]) -> bool:
        """
        Check if an order can be updated (not filled, not cancelled).
        
        Args:
            order: Order dict from Binance
            
        Returns:
            True if order is active and can be modified
        """
        status = order.get("status", "").upper()
        # Only NEW/PARTIALLY_FILLED orders can be modified
        return status in ("NEW", "PARTIALLY_FILLED")
    
    def match_tp_to_existing(
        self,
        new_tp_prices: List[float],
        existing_tp_orders: List[Dict[str, Any]]
    ) -> Dict[int, str]:
        """
        Match new TP prices to existing orders for update.
        
        Args:
            new_tp_prices: New TP prices [TP1, TP2, TP3, TP4, TP5]
            existing_tp_orders: Existing TP orders from Binance
            
        Returns:
            Dict mapping {idx: order_id} for update operations
        """
        mapping = {}
        
        for idx, new_price in enumerate(new_tp_prices):
            if idx < len(existing_tp_orders):
                # Match to existing order by index
                order = existing_tp_orders[idx]
                if self.can_update_order(order):
                    mapping[idx] = order.get("orderId")
        
        return mapping
    
    def consolidate_tp_orders(
        self,
        symbol: str,
        new_tp_prices: List[float],
        new_tp_quantities: List[float],
        existing_tp_orders: List[Dict[str, Any]],
        futures_edit_order,
        futures_create_order,
        exit_side: str,
        position_side: str
    ) -> Dict[str, Any]:
        """
        Consolidate TP orders: UPDATE existing, CREATE new if needed.
        
        This avoids the 10-order limit by reusing existing order slots.
        
        Args:
            symbol: Trading symbol
            new_tp_prices: List of new TP prices
            new_tp_quantities: List of new TP quantities
            existing_tp_orders: Existing TP orders from Binance
            futures_edit_order: Binance API function to edit orders
            futures_create_order: Binance API function to create orders
            exit_side: SELL (for LONG) or BUY (for SHORT)
            position_side: LONG or SHORT
            
        Returns:
            Dict with {updated: [], created: [], failed: []}
        """
        result = {
            "updated": [],
            "created": [],
            "failed": []
        }
        
        try:
            # Step 1: Update existing orders with new prices
            for idx, new_price in enumerate(new_tp_prices):
                if idx < len(existing_tp_orders):
                    order = existing_tp_orders[idx]
                    order_id = order.get("orderId")
                    
                    if not self.can_update_order(order):
                        self.logger.warning(
                            f"⏸️ {symbol} TP{idx+1} order {order_id} "
                            f"is {order.get('status')} - cannot update, will retry on next cycle"
                        )
                        result["failed"].append({"idx": idx+1, "order_id": order_id, "reason": "not_active"})
                        continue
                    
                    # Try to update the order price
                    try:
                        old_price = float(order.get("stopPrice", 0))
                        new_qty = new_tp_quantities[idx] if idx < len(new_tp_quantities) else 0
                        
                        # Only update if price changed significantly (> 0.01%)
                        if old_price > 0:
                            price_change_pct = abs(new_price - old_price) / old_price
                        else:
                            price_change_pct = 0.1
                        
                        if price_change_pct > 0.0001:  # 0.01% threshold
                            # Edit order: Update stopPrice
                            edit_result = futures_edit_order(
                                symbol=symbol,
                                orderId=order_id,
                                stopPrice=new_price,
                                quantity=new_qty if new_qty > 0 else None,
                                side=exit_side,
                                type="TAKE_PROFIT_MARKET",
                                reduceOnly=True,
                                positionSide=position_side
                            )
                            
                            self.logger.info(
                                f"✅ {symbol} TP{idx+1} UPDATED: {old_price:.8f} → {new_price:.8f} "
                                f"(qty={new_qty:.8f})"
                            )
                            result["updated"].append({
                                "idx": idx+1,
                                "order_id": order_id,
                                "old_price": old_price,
                                "new_price": new_price
                            })
                        else:
                            self.logger.debug(
                                f"⏸️ {symbol} TP{idx+1}: Price unchanged (within 0.01%), skipping update"
                            )
                    
                    except Exception as edit_err:
                        self.logger.warning(
                            f"⚠️ {symbol} TP{idx+1} edit failed: {edit_err} - will retry next cycle"
                        )
                        result["failed"].append({
                            "idx": idx+1,
                            "order_id": order_id,
                            "reason": str(edit_err)
                        })
                
                else:
                    # No existing order for this TP level - CREATE new
                    try:
                        new_qty = new_tp_quantities[idx] if idx < len(new_tp_quantities) else 0
                        
                        if new_qty > 0:
                            create_result = futures_create_order(
                                symbol=symbol,
                                side=exit_side,
                                type="TAKE_PROFIT_MARKET",
                                quantity=str(new_qty),
                                stopPrice=new_price,
                                reduceOnly=True,
                                positionSide=position_side
                            )
                            
                            self.logger.info(
                                f"✅ {symbol} TP{idx+1} CREATED: {new_price:.8f} (qty={new_qty:.8f})"
                            )
                            result["created"].append({
                                "idx": idx+1,
                                "price": new_price,
                                "qty": new_qty
                            })
                        else:
                            self.logger.warning(f"⚠️ {symbol} TP{idx+1}: qty=0, skipping create")
                    
                    except Exception as create_err:
                        self.logger.warning(
                            f"⚠️ {symbol} TP{idx+1} create failed: {create_err} "
                            f"(may be at 10-order limit, will retry)"
                        )
                        result["failed"].append({
                            "idx": idx+1,
                            "reason": str(create_err)
                        })
            
        except Exception as consolidate_err:
            self.logger.error(f"❌ {symbol}: Order consolidation failed: {consolidate_err}")
            result["failed"].append({"reason": str(consolidate_err)})
        
        return result
    
    def get_consolidation_summary(self, result: Dict[str, Any]) -> str:
        """Generate summary message for consolidation result."""
        updated = len(result.get("updated", []))
        created = len(result.get("created", []))
        failed = len(result.get("failed", []))
        
        parts = []
        if updated > 0:
            parts.append(f"✅ {updated} updated")
        if created > 0:
            parts.append(f"✨ {created} created")
        if failed > 0:
            parts.append(f"❌ {failed} failed")
        
        return " | ".join(parts) if parts else "⏸️ No changes"


# Global singleton instance
_engine = None


def get_order_consolidation_engine() -> OrderConsolidationEngine:
    """Get or create the global Order Consolidation Engine."""
    global _engine
    if _engine is None:
        _engine = OrderConsolidationEngine()
    return _engine
