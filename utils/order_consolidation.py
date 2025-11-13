#!/usr/bin/env python3
# utils/order_consolidation.py
"""
Order Consolidation System
==========================

Optimizes order management across entire portfolio:
- Maximum 4 active TP/SL orders per symbol
- Consolidates similar prices
- Removes redundant orders
- Optimizes order spacing
- Auto-cleanup schedule

Based on: attached_assets/Pasted--Orders-Orders--1763042905010_1763042905014.txt
"""

import os
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone

logger = logging.getLogger("algogpt.order_consolidation")

# Configuration
MAX_ORDERS_PER_SYMBOL = int(os.getenv("MAX_ORDERS_PER_SYMBOL", "4"))
MIN_ORDER_DISTANCE_PCT = float(os.getenv("MIN_ORDER_DISTANCE_PCT", "0.01"))  # 1%
CONSOLIDATE_THRESHOLD_PCT = float(os.getenv("CONSOLIDATE_THRESHOLD_PCT", "0.003"))  # 0.3%


class OrderConsolidationSystem:
    """
    System-wide order optimization
    
    Usage:
        consolidator = OrderConsolidationSystem()
        await consolidator.optimize_all_symbols()
    """
    
    def __init__(self):
        self.max_orders = MAX_ORDERS_PER_SYMBOL
        self.min_distance = MIN_ORDER_DISTANCE_PCT
        self.consolidate_threshold = CONSOLIDATE_THRESHOLD_PCT
        
        logger.info(
            f"🔧 Order Consolidation System initialized | "
            f"Max Orders: {self.max_orders} | "
            f"Min Distance: {self.min_distance*100:.1f}% | "
            f"Consolidate Threshold: {self.consolidate_threshold*100:.2f}%"
        )
    
    async def optimize_symbol_orders(
        self,
        symbol: str,
        current_orders: List[Dict[str, Any]],
        current_price: float
    ) -> Dict[str, Any]:
        """
        Optimize orders for a single symbol
        
        Args:
            symbol: Trading symbol
            current_orders: List of current open orders
            current_price: Current market price
            
        Returns:
            {
                "symbol": str,
                "before_count": int,
                "after_count": int,
                "actions": [
                    {"type": "cancel", "order_id": str, "reason": str},
                    {"type": "consolidate", "orders": [...], "new_price": float},
                    ...
                ],
                "optimized_orders": [...]
            }
        """
        if not current_orders:
            return {
                "symbol": symbol,
                "before_count": 0,
                "after_count": 0,
                "actions": [],
                "optimized_orders": []
            }
        
        # Separate by order type
        tp_orders = [o for o in current_orders if self._is_tp_order(o)]
        sl_orders = [o for o in current_orders if self._is_sl_order(o)]
        other_orders = [o for o in current_orders if not (self._is_tp_order(o) or self._is_sl_order(o))]
        
        actions = []
        
        # 1. Consolidate similar prices
        optimized_tp, tp_actions = self._consolidate_similar_orders(tp_orders, "TP")
        optimized_sl, sl_actions = self._consolidate_similar_orders(sl_orders, "SL")
        actions.extend(tp_actions)
        actions.extend(sl_actions)
        
        # 2. Optimize TP levels (max 3)
        if len(optimized_tp) > 3:
            optimized_tp, reduce_actions = self._optimize_tp_levels(optimized_tp, current_price)
            actions.extend(reduce_actions)
        
        # 3. Check order spacing
        spacing_actions = self._check_order_spacing(optimized_tp, current_price)
        actions.extend(spacing_actions)
        
        # Combine optimized orders
        optimized_orders = optimized_tp + optimized_sl + other_orders
        
        logger.info(
            f"🔧 {symbol}: Optimized {len(current_orders)} → {len(optimized_orders)} orders "
            f"({len(actions)} actions)"
        )
        
        return {
            "symbol": symbol,
            "before_count": len(current_orders),
            "after_count": len(optimized_orders),
            "actions": actions,
            "optimized_orders": optimized_orders
        }
    
    def _is_tp_order(self, order: Dict[str, Any]) -> bool:
        """Check if order is a take-profit order"""
        order_type = order.get("type", "").upper()
        return "TAKE_PROFIT" in order_type or "TP" in order.get("clientOrderId", "")
    
    def _is_sl_order(self, order: Dict[str, Any]) -> bool:
        """Check if order is a stop-loss order"""
        order_type = order.get("type", "").upper()
        return "STOP" in order_type and "TAKE" not in order_type or "SL" in order.get("clientOrderId", "")
    
    def _consolidate_similar_orders(
        self, 
        orders: List[Dict[str, Any]], 
        order_group: str
    ) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """
        Consolidate orders with similar prices
        
        Returns:
            (optimized_orders, actions)
        """
        if len(orders) <= 1:
            return orders, []
        
        # Sort by price
        orders_sorted = sorted(orders, key=lambda o: float(o.get("stopPrice", o.get("price", 0))))
        
        consolidated = []
        actions = []
        skip_indices = set()
        
        for i, order in enumerate(orders_sorted):
            if i in skip_indices:
                continue
            
            price_i = float(order.get("stopPrice", order.get("price", 0)))
            qty_i = float(order.get("origQty", 0))
            
            # Find similar orders
            similar = [order]
            for j in range(i + 1, len(orders_sorted)):
                if j in skip_indices:
                    continue
                
                price_j = float(orders_sorted[j].get("stopPrice", orders_sorted[j].get("price", 0)))
                
                # Check if within consolidation threshold
                if price_i > 0 and abs(price_j - price_i) / price_i < self.consolidate_threshold:
                    similar.append(orders_sorted[j])
                    skip_indices.add(j)
            
            # If multiple similar orders, consolidate
            if len(similar) > 1:
                # Calculate average price weighted by quantity
                total_qty = sum(float(o.get("origQty", 0)) for o in similar)
                avg_price = sum(
                    float(o.get("stopPrice", o.get("price", 0))) * float(o.get("origQty", 0))
                    for o in similar
                ) / total_qty if total_qty > 0 else price_i
                
                # Create consolidated order (use first as template)
                consolidated_order = similar[0].copy()
                consolidated_order["price"] = avg_price
                consolidated_order["origQty"] = total_qty
                consolidated.append(consolidated_order)
                
                actions.append({
                    "type": "consolidate",
                    "order_group": order_group,
                    "orders": [o.get("orderId") for o in similar],
                    "new_price": avg_price,
                    "new_qty": total_qty,
                    "reason": f"Consolidated {len(similar)} {order_group} orders with similar prices"
                })
            else:
                consolidated.append(order)
        
        return consolidated, actions
    
    def _optimize_tp_levels(
        self, 
        tp_orders: List[Dict[str, Any]], 
        current_price: float
    ) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """
        Optimize TP levels to maximum 3
        
        Returns:
            (optimized_orders, actions)
        """
        if len(tp_orders) <= 3:
            return tp_orders, []
        
        # Sort by distance from current price
        tp_sorted = sorted(
            tp_orders,
            key=lambda o: abs(float(o.get("stopPrice", o.get("price", 0))) - current_price)
        )
        
        # Keep 3 most strategic (closest, middle, furthest)
        if len(tp_sorted) >= 3:
            keep = [
                tp_sorted[0],  # Closest (TP1)
                tp_sorted[len(tp_sorted) // 2],  # Middle (TP2)
                tp_sorted[-1]  # Furthest (TP3)
            ]
        else:
            keep = tp_sorted[:3]
        
        # Cancel the rest
        cancel = [o for o in tp_sorted if o not in keep]
        
        actions = [{
            "type": "cancel",
            "order_id": o.get("orderId"),
            "reason": f"Reducing TP orders to 3 strategic levels"
        } for o in cancel]
        
        return keep, actions
    
    def _check_order_spacing(
        self, 
        orders: List[Dict[str, Any]], 
        current_price: float
    ) -> List[Dict[str, Any]]:
        """
        Check if orders have minimum distance between them
        
        Returns:
            List of warning actions
        """
        if len(orders) <= 1 or current_price <= 0:
            return []
        
        actions = []
        orders_sorted = sorted(
            orders,
            key=lambda o: float(o.get("stopPrice", o.get("price", 0)))
        )
        
        for i in range(len(orders_sorted) - 1):
            price_i = float(orders_sorted[i].get("stopPrice", orders_sorted[i].get("price", 0)))
            price_j = float(orders_sorted[i + 1].get("stopPrice", orders_sorted[i + 1].get("price", 0)))
            
            if price_i > 0:
                distance = abs(price_j - price_i) / price_i
                if distance < self.min_distance:
                    actions.append({
                        "type": "warning",
                        "reason": f"Orders too close ({distance*100:.2f}% < {self.min_distance*100:.1f}%)",
                        "orders": [
                            orders_sorted[i].get("orderId"),
                            orders_sorted[i + 1].get("orderId")
                        ]
                    })
        
        return actions
    
    def get_consolidation_stats(self) -> Dict[str, Any]:
        """Get consolidation system stats"""
        return {
            "max_orders_per_symbol": self.max_orders,
            "min_distance_pct": f"{self.min_distance*100:.1f}%",
            "consolidate_threshold_pct": f"{self.consolidate_threshold*100:.2f}%",
            "rules": {
                "1_order_consolidation": "Maximum 4 active TP/SL orders per symbol",
                "2_order_type_optimization": "Use MARKET for TP, LIMIT for entries",
                "3_trailing_tp": "Auto-convert static TP to trailing above 25% profit",
                "4_risk_aware": "Minimum 1% distance between TP levels",
                "5_auto_cleanup": "Daily order book optimization"
            }
        }


# Singleton instance
_consolidator: Optional[OrderConsolidationSystem] = None


def get_order_consolidator() -> OrderConsolidationSystem:
    """Get or create singleton consolidator instance"""
    global _consolidator
    if _consolidator is None:
        _consolidator = OrderConsolidationSystem()
    return _consolidator
