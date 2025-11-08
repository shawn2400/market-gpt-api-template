"""
Emergency Protection System - 100% Trade Safety Guarantee
==========================================================
3-Layer protection system that ensures EVERY position has SL+TP:

Layer 1: Post-Entry Verification (2 seconds after entry)
Layer 2: Continuous Monitoring (every 15 seconds)
Layer 3: Emergency Close + Circuit Breaker

CRITICAL: If position lacks SL/TP → Close immediately + Pause system
"""

import logging
import time
from typing import Dict, List, Optional, Tuple
import os

logger = logging.getLogger("emergency_protection")

try:
    from utils.binance_client import get_client, futures_get_open_orders, futures_get_position, futures_create_order
    BINANCE_AVAILABLE = True
except ImportError:
    logger.warning("Binance client not available")
    BINANCE_AVAILABLE = False

try:
    from utils.telegram_notifier import notify_telegram
    TELEGRAM_AVAILABLE = True
except ImportError:
    logger.warning("Telegram notifier not available")
    TELEGRAM_AVAILABLE = False


class EmergencyProtection:
    """
    Emergency protection system that enforces 100% SL/TP coverage
    """
    
    def __init__(self):
        self.unprotected_count = 0
        self.circuit_breaker_threshold = 2
        self.last_check_time = 0
        self.emergency_closes = []
        
    def verify_protection(self, symbol: str, side: str, position_qty: float, position_side: str = "BOTH") -> Tuple[bool, str]:
        """
        Verify that a position has both SL and TP orders
        
        🛡️ CRITICAL FIX: Checks protection per (symbol, positionSide) in Hedge Mode!
        
        Args:
            symbol: Trading pair
            side: BUY/SELL or LONG/SHORT
            position_qty: Position quantity
            position_side: LONG/SHORT/BOTH (for Hedge Mode compatibility)
        
        Returns:
            (has_protection, details)
        """
        if not BINANCE_AVAILABLE:
            return False, "Binance client unavailable"
        
        try:
            client = get_client()
            orders = futures_get_open_orders(symbol=symbol)
            
            sl_types = ['STOP', 'STOP_MARKET', 'STOP_LOSS', 'STOP_LOSS_LIMIT']
            tp_types = ['TAKE_PROFIT', 'TAKE_PROFIT_MARKET', 'TAKE_PROFIT_LIMIT']
            
            sl_orders = []
            tp_orders = []
            
            # 📊 ENHANCED LOGGING: Log ALL orders found
            logger.info(f"🔍 Verifying protection for {symbol} {side} qty={position_qty} positionSide={position_side}")
            logger.info(f"📋 Found {len(orders)} open orders for {symbol}")
            
            # 🛡️ CRITICAL: Filter orders by positionSide for Hedge Mode
            # In Hedge Mode: LONG position needs SELL reduceOnly orders
            # In Hedge Mode: SHORT position needs BUY reduceOnly orders
            relevant_orders = []
            
            for order in orders:
                order_type = order.get('type', '')
                order_id = order.get('orderId', 'N/A')
                order_side = order.get('side', 'N/A')
                order_position_side = order.get('positionSide', 'BOTH')
                reduce_only = order.get('reduceOnly', False)
                stop_price = order.get('stopPrice', 'N/A')
                status = order.get('status', 'N/A')
                
                # 📝 LOG: Every order with full details
                logger.info(
                    f"   Order #{order_id}: {order_type} {order_side} "
                    f"positionSide={order_position_side} reduceOnly={reduce_only} "
                    f"stopPrice={stop_price} status={status}"
                )
                
                # 🛡️ Hedge Mode: Check if order belongs to THIS position side
                if position_side != "BOTH":
                    # In Hedge Mode, check positionSide match OR reduceOnly + correct closing side
                    if order_position_side == position_side:
                        relevant_orders.append(order)
                    elif reduce_only:
                        # LONG position → needs SELL reduceOnly
                        # SHORT position → needs BUY reduceOnly
                        if (position_side == "LONG" and order_side == "SELL") or \
                           (position_side == "SHORT" and order_side == "BUY"):
                            relevant_orders.append(order)
                else:
                    # One-Way Mode: all reduceOnly orders are relevant
                    if reduce_only or order_position_side == "BOTH":
                        relevant_orders.append(order)
            
            logger.info(f"   → {len(relevant_orders)} orders relevant for {position_side} side")
            
            # 🛡️ CRITICAL: Sum up total protected quantities
            total_sl_qty = 0.0
            total_tp_qty = 0.0
            has_sl_close_position = False
            has_tp_close_position = False
            
            for order in relevant_orders:
                order_type = order.get('type', '')
                order_id = order.get('orderId', 'N/A')
                close_position = order.get('closePosition', False)
                orig_qty = abs(float(order.get('origQty', 0)))
                executed_qty = abs(float(order.get('executedQty', 0)))
                remaining_qty = orig_qty - executed_qty  # 🛡️ Only count unfilled qty
                stop_price = order.get('stopPrice', 'N/A')
                
                if order_type in sl_types:
                    sl_orders.append(order_id)
                    
                    # 🛡️ CRITICAL FIX: closePosition=True means it covers the ENTIRE position
                    if close_position:
                        has_sl_close_position = True
                        logger.info(f"   ✅ SL order for {position_side}: #{order_id} closePosition=True @ {stop_price}")
                    else:
                        total_sl_qty += remaining_qty
                        logger.info(f"   ✅ SL order for {position_side}: #{order_id} qty={remaining_qty:.4f} (orig={orig_qty}, exec={executed_qty}) @ {stop_price}")
                
                if order_type in tp_types:
                    tp_orders.append(order_id)
                    
                    # 🛡️ CRITICAL FIX: closePosition=True means it covers the ENTIRE position
                    if close_position:
                        has_tp_close_position = True
                        logger.info(f"   ✅ TP order for {position_side}: #{order_id} closePosition=True @ {stop_price}")
                    else:
                        total_tp_qty += remaining_qty
                        logger.info(f"   ✅ TP order for {position_side}: #{order_id} qty={remaining_qty:.4f} (orig={orig_qty}, exec={executed_qty}) @ {stop_price}")
            
            # 🛡️ CRITICAL FIX: Check protection
            # Either closePosition=True OR total qty >= position qty
            required_qty = abs(position_qty)
            
            has_sl = has_sl_close_position or (total_sl_qty >= required_qty * 0.999)
            has_tp = has_tp_close_position or (total_tp_qty >= required_qty * 0.999)
            
            # 📊 SUMMARY LOG
            if has_sl and has_tp:
                logger.info(
                    f"✅ {symbol} {position_side} PROTECTED: SL qty={total_sl_qty:.4f}/{required_qty:.4f}, "
                    f"TP qty={total_tp_qty:.4f}/{required_qty:.4f}"
                )
                return True, f"✅ Protected: SL={total_sl_qty:.4f}, TP={total_tp_qty:.4f}"
            else:
                logger.critical(
                    f"🚨 {symbol} {position_side} INSUFFICIENT PROTECTION: "
                    f"SL qty={total_sl_qty:.4f}/{required_qty:.4f} ({total_sl_qty>=required_qty*0.999}), "
                    f"TP qty={total_tp_qty:.4f}/{required_qty:.4f} ({total_tp_qty>=required_qty*0.999})"
                )
                return False, f"🚨 INSUFFICIENT: SL={total_sl_qty:.4f}/{required_qty:.4f}, TP={total_tp_qty:.4f}/{required_qty:.4f}"
                
        except Exception as e:
            logger.error(f"Failed to verify protection for {symbol}: {e}")
            return False, f"Error: {e}"
    
    def emergency_close_position(self, symbol: str, side: str, qty: float, reason: str, position_side: str = "BOTH") -> bool:
        """
        Emergency market close of unprotected position
        
        🛡️ CRITICAL FIX: Supports Hedge Mode by sending positionSide to Binance!
        
        Args:
            symbol: Trading pair
            side: BUY/SELL or LONG/SHORT
            qty: Position quantity
            reason: Why we're closing
            position_side: LONG/SHORT/BOTH for Hedge Mode
        
        Returns:
            True if successfully closed
        """
        if not BINANCE_AVAILABLE:
            # 🔴 CRITICAL FIX: Raise exception instead of returning False!
            logger.critical(f"🔴🔴🔴 FATAL: Cannot close {symbol} - Binance unavailable!")
            raise RuntimeError(f"Cannot emergency close {symbol} - Binance client unavailable")
        
        try:
            logger.critical(f"🚨 EMERGENCY CLOSE: {symbol} {side} positionSide={position_side} qty={qty} - Reason: {reason}")
            
            close_side = 'SELL' if side in ('LONG', 'BUY') else 'BUY'
            
            # 🛡️ CRITICAL FIX: Add positionSide for Hedge Mode support
            order_params = {
                'symbol': symbol,
                'side': close_side,
                'type': 'MARKET',
                'quantity': abs(qty),
                'reduceOnly': True
            }
            
            # Only add positionSide if not in One-Way mode
            if position_side != "BOTH":
                order_params['positionSide'] = position_side
            
            result = futures_create_order(**order_params)
            
            logger.info(f"✅ {symbol} {position_side} emergency closed: Order #{result.get('orderId')}")
            
            self.emergency_closes.append({
                'symbol': symbol,
                'side': side,
                'position_side': position_side,
                'qty': qty,
                'reason': reason,
                'timestamp': time.time()
            })
            
            if TELEGRAM_AVAILABLE:
                msg = (
                    f"🚨 <b>EMERGENCY CLOSE</b>\n"
                    f"📊 {symbol} {side}\n"
                    f"📦 Qty: {qty}\n"
                    f"⚠️ Reason: {reason}\n"
                    f"🔴 Position closed at MARKET price to prevent loss"
                )
                try:
                    import asyncio
                    
                    # 🛡️ FIX: Use create_task if in async context, otherwise run_until_complete
                    try:
                        loop = asyncio.get_running_loop()
                        # We're in an async context - schedule task without blocking
                        asyncio.create_task(notify_telegram(msg, level="critical", kind="emergency"))
                        logger.info("Telegram alert scheduled via create_task")
                    except RuntimeError:
                        # No running loop - safe to use run_until_complete
                        loop = asyncio.new_event_loop()
                        asyncio.set_event_loop(loop)
                        loop.run_until_complete(notify_telegram(msg, level="critical", kind="emergency"))
                        logger.info("Telegram alert sent via run_until_complete")
                except Exception as e:
                    logger.warning(f"Failed to send telegram alert: {e}")
            
            return True
            
        except Exception as e:
            # 🔴 CRITICAL FIX: Raise exception instead of returning False silently!
            logger.critical(f"🔴🔴🔴 FATAL: Failed to emergency close {symbol} {position_side}: {e}")
            logger.critical(f"🔴 Position remains LIVE and UNPROTECTED!")
            raise RuntimeError(f"Emergency close FAILED for {symbol} {position_side}: {e}")
    
    def check_all_positions(self) -> List[Dict]:
        """
        Check all open positions for SL/TP protection
        
        🛡️ CRITICAL FIX: Checks each (symbol, positionSide) separately in Hedge Mode!
        
        Returns:
            List of unprotected positions
        """
        if not BINANCE_AVAILABLE:
            return []
        
        unprotected = []
        
        try:
            client = get_client()
            positions = client.futures_position_information()
            
            for pos in positions:
                qty = float(pos.get('positionAmt', 0))
                if abs(qty) < 0.0001:
                    continue
                
                symbol = pos['symbol']
                side = 'LONG' if qty > 0 else 'SHORT'
                position_side = pos.get('positionSide', 'BOTH')  # 🛡️ Get positionSide for Hedge Mode
                
                # 🛡️ CRITICAL: Pass positionSide to verify_protection
                has_protection, details = self.verify_protection(
                    symbol=symbol,
                    side=side,
                    position_qty=qty,
                    position_side=position_side
                )
                
                if not has_protection:
                    logger.warning(f"🚨 {symbol} {side} (positionSide={position_side}) UNPROTECTED: {details}")
                    unprotected.append({
                        'symbol': symbol,
                        'side': side,
                        'position_side': position_side,  # 🛡️ Include positionSide
                        'qty': qty,
                        'details': details,
                        'entry': float(pos.get('entryPrice', 0))
                    })
                else:
                    logger.debug(f"✅ {symbol} {side} (positionSide={position_side}) {details}")
            
            return unprotected
            
        except Exception as e:
            logger.error(f"Failed to check positions: {e}")
            return []
    
    def enforce_protection(self) -> int:
        """
        Main enforcement loop - checks positions and closes unprotected ones
        
        Returns:
            Number of positions emergency closed
        """
        unprotected = self.check_all_positions()
        closed_count = 0
        
        if unprotected:
            logger.critical(f"🚨 FOUND {len(unprotected)} UNPROTECTED POSITIONS!")
            
            for pos in unprotected:
                # 🛡️ CRITICAL FIX: Pass positionSide for Hedge Mode
                try:
                    self.emergency_close_position(
                        symbol=pos['symbol'],
                        side=pos['side'],
                        qty=pos['qty'],
                        reason=f"Missing SL/TP protection - {pos['details']}",
                        position_side=pos.get('position_side', 'BOTH')
                    )
                    
                    # Success - emergency close worked
                    closed_count += 1
                    self.unprotected_count += 1
                    
                except RuntimeError as e:
                    # 🔴 CRITICAL: Emergency close FAILED (exception raised)!
                    logger.critical(f"🔴🔴🔴 LAYER 3: Emergency close FAILED for {pos['symbol']} {pos.get('position_side', 'BOTH')}: {e}")
                    self.unprotected_count += 2  # Escalate more since this is continuous monitoring failure
                    logger.critical(f"🔴 Unprotected count ESCALATED to {self.unprotected_count} (Layer 3 failure)")
                    
                    # FORCE circuit breaker immediately on Layer 3 failure
                    logger.critical(f"🔴 FORCING CIRCUIT BREAKER due to Layer 3 emergency close failure!")
                    self.trigger_circuit_breaker()
                    
                    # Continue to next position (don't crash the loop)
            
            if self.unprotected_count >= self.circuit_breaker_threshold:
                logger.critical(f"🔴 CIRCUIT BREAKER TRIGGERED! {self.unprotected_count} unprotected positions detected")
                self.trigger_circuit_breaker()
        
        return closed_count
    
    def trigger_circuit_breaker(self):
        """
        Trigger circuit breaker - pause all trading
        """
        logger.critical("🔴 CIRCUIT BREAKER: Pausing all trading activities")
        
        try:
            os.environ['PAUSE_AUTO_RUN'] = '1'
            
            if TELEGRAM_AVAILABLE:
                msg = (
                    f"🔴 <b>CIRCUIT BREAKER ACTIVATED</b>\n\n"
                    f"⚠️ System detected {self.unprotected_count} unprotected positions\n"
                    f"🛑 All trading has been PAUSED\n"
                    f"📋 Emergency closes executed: {len(self.emergency_closes)}\n\n"
                    f"<b>Action Required:</b>\n"
                    f"1. Review emergency closes log\n"
                    f"2. Investigate why SL/TP were missing\n"
                    f"3. Fix the issue\n"
                    f"4. Set PAUSE_AUTO_RUN=0 to resume\n\n"
                    f"🚨 DO NOT RESUME until issue is resolved!"
                )
                try:
                    import asyncio
                    
                    # 🛡️ FIX: Use create_task if in async context
                    try:
                        loop = asyncio.get_running_loop()
                        asyncio.create_task(notify_telegram(msg, level="critical", kind="circuit_breaker"))
                        logger.info("Circuit breaker alert scheduled via create_task")
                    except RuntimeError:
                        loop = asyncio.new_event_loop()
                        asyncio.set_event_loop(loop)
                        loop.run_until_complete(notify_telegram(msg, level="critical", kind="circuit_breaker"))
                        logger.info("Circuit breaker alert sent via run_until_complete")
                except Exception as e:
                    logger.warning(f"Failed to send circuit breaker alert: {e}")
            
        except Exception as e:
            logger.error(f"Failed to trigger circuit breaker: {e}")
    
    def post_entry_verification(self, symbol: str, side: str, qty: float, position_side: str = "BOTH", max_wait_sec: int = 3) -> bool:
        """
        Verify protection immediately after entry (within 2-3 seconds)
        
        🛡️ CRITICAL: Supports Hedge Mode by checking positionSide
        🔴 CRITICAL: Activates Circuit Breaker if protection missing!
        
        Args:
            symbol: Trading pair
            side: BUY/SELL or LONG/SHORT
            qty: Position quantity
            position_side: LONG/SHORT/BOTH for Hedge Mode
            max_wait_sec: Seconds to wait before checking
        
        Returns:
            True if protected, False if emergency close was needed
        """
        logger.info(f"🔍 Post-entry verification for {symbol} {side} positionSide={position_side}...")
        
        time.sleep(2)
        
        # 🛡️ Pass positionSide to verify_protection
        has_protection, details = self.verify_protection(symbol, side, qty, position_side)
        
        if has_protection:
            logger.info(f"✅ {symbol} {position_side} post-entry verification PASSED: {details}")
            return True
        else:
            logger.critical(f"🚨 {symbol} {position_side} post-entry verification FAILED: {details}")
            
            # 🔴 CRITICAL FIX: Increment violation counter
            self.unprotected_count += 1
            logger.critical(f"🔴 Unprotected count increased to {self.unprotected_count}")
            
            # Emergency close - now raises RuntimeError on failure!
            # 🛡️ CRITICAL FIX: Pass positionSide for Hedge Mode
            try:
                self.emergency_close_position(
                    symbol=symbol,
                    side=side,
                    qty=qty,
                    reason=f"Post-entry verification failed - {details}",
                    position_side=position_side
                )
                
                # If we get here, close succeeded
                logger.info(f"✅ {symbol} {position_side} emergency close succeeded")
                
            except RuntimeError as e:
                # 🔴 CRITICAL: Emergency close FAILED (exception raised)!
                logger.critical(f"🔴🔴🔴 LAYER 2: EMERGENCY CLOSE FAILED for {symbol} {position_side}: {e}")
                self.unprotected_count += 1  # Increment again for failed close
                logger.critical(f"🔴 Unprotected count ESCALATED to {self.unprotected_count} due to failed emergency close")
                
                # ALWAYS trigger circuit breaker when emergency close fails
                logger.critical(f"🔴 FORCING CIRCUIT BREAKER due to failed emergency close!")
                self.trigger_circuit_breaker()
                
                # Re-raise to surface to auto_execute_plan
                raise
            
            # 🔴 CRITICAL FIX: Trigger circuit breaker if threshold reached
            if self.unprotected_count >= self.circuit_breaker_threshold:
                logger.critical(f"🔴 Circuit breaker threshold reached! ({self.unprotected_count} >= {self.circuit_breaker_threshold})")
                self.trigger_circuit_breaker()
            
            return False


_emergency_protection_instance: Optional[EmergencyProtection] = None

def get_emergency_protection() -> EmergencyProtection:
    """Get singleton instance"""
    global _emergency_protection_instance
    if _emergency_protection_instance is None:
        _emergency_protection_instance = EmergencyProtection()
    return _emergency_protection_instance
