#!/usr/bin/env python3
"""
Live Position Manager - Dynamic SL/TP Management
=================================================
LIVE and DYNAMIC position management - moves orders in real-time on exchange!

Features:
- Real-time SL/TP updates on Binance
- Break-even automation
- Trailing stop automation
- Visible immediately on exchange (NOT static!)
- AI-driven dynamic adjustments
"""

import logging
import os
from typing import Dict, Any, Optional
from decimal import Decimal
import time

logger = logging.getLogger("algogpt.live_position")


class LivePositionManager:
    """
    Manages open positions with LIVE SL/TP updates on exchange.
    
    This is NOT static - orders are actively moved in real-time!
    Users see changes immediately on Binance.
    """
    
    def __init__(self, binance_client=None):
        self.logger = logger
        self.client = binance_client
        
        self.be_enabled = os.getenv("TRAIL_ENABLE", "1") == "1"
        self.trailing_enabled = os.getenv("TRAIL_ENABLE", "1") == "1"
        
        self.logger.info(
            f"Live Position Manager initialized | "
            f"BE={'ON' if self.be_enabled else 'OFF'}, "
            f"Trailing={'ON' if self.trailing_enabled else 'OFF'}"
        )
    
    def update_stop_loss_live(
        self,
        symbol: str,
        order_id: str,
        new_sl_price: float,
        direction: str
    ) -> bool:
        """
        Update stop loss LIVE on Binance exchange.
        
        Args:
            symbol: Trading pair
            order_id: Existing SL order ID
            new_sl_price: New stop loss price
            direction: LONG or SHORT
        
        Returns:
            True if updated successfully
        """
        try:
            if not self.client:
                self.logger.warning(f"No Binance client - mock SL update to {new_sl_price}")
                return True
            
            self.client.futures_cancel_order(symbol=symbol, orderId=order_id)
            self.logger.debug(f"Cancelled old SL order {order_id}")
            
            side = "SELL" if direction == "LONG" else "BUY"
            
            new_order = self.client.futures_create_order(
                symbol=symbol,
                side=side,
                type="STOP_MARKET",
                stopPrice=new_sl_price,
                closePosition=True
            )
            
            new_order_id = new_order.get("orderId")
            
            self.logger.info(
                f"✅ SL updated LIVE on exchange: {symbol} → ${new_sl_price:.2f} "
                f"(Order #{new_order_id})"
            )
            
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to update SL for {symbol}: {e}", exc_info=True)
            return False
    
    def update_take_profit_live(
        self,
        symbol: str,
        order_id: str,
        new_tp_price: float,
        direction: str,
        quantity: float
    ) -> bool:
        """
        Update take profit LIVE on Binance exchange.
        
        Args:
            symbol: Trading pair
            order_id: Existing TP order ID
            new_tp_price: New take profit price
            direction: LONG or SHORT
            quantity: Position quantity
        
        Returns:
            True if updated successfully
        """
        try:
            if not self.client:
                self.logger.warning(f"No Binance client - mock TP update to {new_tp_price}")
                return True
            
            self.client.futures_cancel_order(symbol=symbol, orderId=order_id)
            self.logger.debug(f"Cancelled old TP order {order_id}")
            
            side = "SELL" if direction == "LONG" else "BUY"
            
            new_order = self.client.futures_create_order(
                symbol=symbol,
                side=side,
                type="LIMIT",
                price=new_tp_price,
                quantity=quantity,
                timeInForce="GTC",
                reduceOnly=True
            )
            
            new_order_id = new_order.get("orderId")
            
            self.logger.info(
                f"✅ TP updated LIVE on exchange: {symbol} → ${new_tp_price:.2f} "
                f"(Order #{new_order_id})"
            )
            
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to update TP for {symbol}: {e}", exc_info=True)
            return False
    
    def move_to_breakeven(
        self,
        symbol: str,
        sl_order_id: str,
        entry_price: float,
        direction: str
    ) -> bool:
        """
        Move stop loss to break-even (entry price).
        
        Args:
            symbol: Trading pair
            sl_order_id: Current SL order ID
            entry_price: Original entry price
            direction: LONG or SHORT
        
        Returns:
            True if moved successfully
        """
        try:
            if not self.be_enabled:
                self.logger.debug("Break-even disabled")
                return False
            
            success = self.update_stop_loss_live(
                symbol=symbol,
                order_id=sl_order_id,
                new_sl_price=entry_price,
                direction=direction
            )
            
            if success:
                self.logger.info(
                    f"🎯 Break-even activated: {symbol} SL → ${entry_price:.2f} "
                    f"(LIVE on exchange!)"
                )
            
            return success
            
        except Exception as e:
            self.logger.error(f"Failed to move to BE for {symbol}: {e}", exc_info=True)
            return False
    
    def apply_trailing_stop(
        self,
        symbol: str,
        sl_order_id: str,
        current_price: float,
        trailing_distance: float,
        direction: str,
        current_sl: float
    ) -> bool:
        """
        Apply trailing stop - moves SL closer as price moves favorably.
        
        Args:
            symbol: Trading pair
            sl_order_id: Current SL order ID
            current_price: Current market price
            trailing_distance: Distance from price to trail
            direction: LONG or SHORT
            current_sl: Current stop loss price
        
        Returns:
            True if trailed successfully
        """
        try:
            if not self.trailing_enabled:
                self.logger.debug("Trailing stop disabled")
                return False
            
            if direction == "LONG":
                new_sl = current_price - trailing_distance
                if new_sl <= current_sl:
                    self.logger.debug(f"LONG: New SL {new_sl:.2f} not better than current {current_sl:.2f}")
                    return False
            else:
                new_sl = current_price + trailing_distance
                if new_sl >= current_sl:
                    self.logger.debug(f"SHORT: New SL {new_sl:.2f} not better than current {current_sl:.2f}")
                    return False
            
            success = self.update_stop_loss_live(
                symbol=symbol,
                order_id=sl_order_id,
                new_sl_price=new_sl,
                direction=direction
            )
            
            if success:
                self.logger.info(
                    f"📉 Trailing stop: {symbol} SL: ${current_sl:.2f} → ${new_sl:.2f} "
                    f"(Distance: ${trailing_distance:.2f}) - LIVE!"
                )
            
            return success
            
        except Exception as e:
            self.logger.error(f"Failed to apply trailing for {symbol}: {e}", exc_info=True)
            return False
    
    def check_and_update_position(
        self,
        position_data: Dict[str, Any],
        market_price: float,
        atr: float
    ) -> Dict[str, Any]:
        """
        Check position and apply dynamic updates (BE, trailing, etc).
        
        Args:
            position_data: Dict with position info (entry, SL, TP, etc)
            market_price: Current market price
            atr: Current ATR
        
        Returns:
            Dict with updates applied
        """
        try:
            symbol = position_data.get("symbol")
            direction = position_data.get("direction")
            entry_price = position_data.get("entry_price", 0)
            sl_order_id = position_data.get("sl_order_id")
            current_sl = position_data.get("current_sl", 0)
            be_moved = position_data.get("be_moved", False)
            
            # Type guards
            if not symbol or not isinstance(symbol, str):
                return {"error": "Missing or invalid symbol"}
            if not direction or not isinstance(direction, str):
                return {"error": "Missing or invalid direction"}
            if not sl_order_id or not isinstance(sl_order_id, str):
                return {"error": "Missing or invalid sl_order_id"}
            
            updates = {
                "be_moved": be_moved,
                "sl_updated": False,
                "tp_updated": False
            }
            
            if not be_moved:
                from config.ai_protections import get_protection_manager
                protection = get_protection_manager()
                
                be_trigger = protection.calculate_breakeven_trigger(
                    entry_price, direction, quality_score=7.0
                )
                
                if direction == "LONG" and market_price >= be_trigger:
                    if self.move_to_breakeven(symbol, sl_order_id, entry_price, direction):
                        updates["be_moved"] = True
                        updates["sl_updated"] = True
                        updates["new_sl"] = entry_price
                
                elif direction == "SHORT" and market_price <= be_trigger:
                    if self.move_to_breakeven(symbol, sl_order_id, entry_price, direction):
                        updates["be_moved"] = True
                        updates["sl_updated"] = True
                        updates["new_sl"] = entry_price
            
            elif be_moved:
                from config.ai_protections import get_protection_manager
                protection = get_protection_manager()
                
                trailing_dist = protection.calculate_trailing_distance(
                    market_price, atr, direction, regime="NEUTRAL"
                )
                
                if self.apply_trailing_stop(
                    symbol, sl_order_id, market_price, 
                    trailing_dist, direction, current_sl
                ):
                    updates["sl_updated"] = True
                    if direction == "LONG":
                        updates["new_sl"] = market_price - trailing_dist
                    else:
                        updates["new_sl"] = market_price + trailing_dist
            
            return updates
            
        except Exception as e:
            self.logger.error(f"Failed to check/update position: {e}", exc_info=True)
            return {"error": str(e)}


_live_manager: Optional[LivePositionManager] = None


def get_live_position_manager(binance_client=None) -> LivePositionManager:
    """Get or create Live Position Manager."""
    global _live_manager
    if _live_manager is None:
        _live_manager = LivePositionManager(binance_client)
    return _live_manager


__all__ = ["LivePositionManager", "get_live_position_manager"]
