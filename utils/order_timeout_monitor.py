# -*- coding: utf-8 -*-
"""
Order Timeout Monitor - LIMIT→MARKET Fallback
==============================================
Monitors unfilled LIMIT orders and converts them to MARKET after timeout.

Features:
- Tracks all LIMIT orders (entry + TP/SL)
- 60-second timeout for unfilled orders
- Automatic cancellation + MARKET order placement
- Thread-safe operation
- Telegram notifications

Author: AlgoGPT Team
"""
from __future__ import annotations
import os
import time
import logging
import threading
from typing import Dict, Any, Optional, Set
from datetime import datetime, timedelta
from collections import defaultdict

logger = logging.getLogger(__name__)

# Configuration
TIMEOUT_ENABLE = os.getenv("LIMIT_TO_MARKET_ENABLE", "1") == "1"
TIMEOUT_SECONDS = int(os.getenv("LIMIT_ORDER_TIMEOUT_SEC", "60"))
CHECK_INTERVAL = int(os.getenv("LIMIT_TIMEOUT_CHECK_INTERVAL", "5"))  # Check every 5s
MAX_RETRY_ATTEMPTS = int(os.getenv("LIMIT_TO_MARKET_MAX_RETRIES", "3"))


class OrderTimeoutMonitor:
    """
    Monitors LIMIT orders and converts unfilled ones to MARKET after timeout.
    
    Usage:
        monitor = OrderTimeoutMonitor(binance_client)
        
        # Register order for monitoring
        monitor.track_order(order_id, symbol, side, quantity, order_type="ENTRY")
        
        # Start monitoring (runs in background thread)
        monitor.start()
    """
    
    def __init__(self, binance_client):
        """
        Args:
            binance_client: Binance client with futures_get_order, futures_cancel_order, futures_create_order
        """
        self.client = binance_client
        self.enabled = TIMEOUT_ENABLE
        self.timeout_sec = TIMEOUT_SECONDS
        
        # Tracked orders: order_id → {symbol, side, qty, created_at, order_type}
        self.tracked_orders: Dict[int, Dict[str, Any]] = {}
        self.processed_orders: Set[int] = set()  # Avoid reprocessing
        
        # Thread control
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        
        logger.info(f"OrderTimeoutMonitor initialized (enabled={self.enabled}, timeout={self.timeout_sec}s)")
    
    def track_order(
        self,
        order_id: int,
        symbol: str,
        side: str,
        quantity: str,
        order_type: str = "ENTRY",  # ENTRY|TP|SL
        position_side: Optional[str] = None
    ) -> None:
        """
        Register LIMIT order for timeout monitoring.
        
        Args:
            order_id: Binance order ID
            symbol: Trading pair
            side: BUY or SELL
            quantity: Order quantity
            order_type: ENTRY, TP, or SL
            position_side: LONG, SHORT, or None (Hedge Mode)
        """
        if not self.enabled:
            return
        
        with self._lock:
            self.tracked_orders[order_id] = {
                "symbol": symbol,
                "side": side,
                "quantity": quantity,
                "order_type": order_type,
                "position_side": position_side,
                "created_at": datetime.now(),
                "retries": 0
            }
            logger.info(f"📝 Tracking LIMIT order {order_id} ({symbol} {side} {quantity}) - timeout in {self.timeout_sec}s")
    
    def start(self) -> None:
        """Start background monitoring thread."""
        if not self.enabled:
            logger.warning("OrderTimeoutMonitor disabled (LIMIT_TO_MARKET_ENABLE=0)")
            return
        
        if self._thread and self._thread.is_alive():
            logger.warning("OrderTimeoutMonitor already running")
            return
        
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._thread.start()
        logger.info("🚀 OrderTimeoutMonitor started")
    
    def stop(self) -> None:
        """Stop monitoring thread."""
        if self._thread and self._thread.is_alive():
            self._stop_event.set()
            self._thread.join(timeout=10)
            logger.info("🛑 OrderTimeoutMonitor stopped")
    
    def _monitor_loop(self) -> None:
        """Background thread that checks orders periodically."""
        logger.info(f"📊 OrderTimeoutMonitor loop started (check interval={CHECK_INTERVAL}s)")
        
        while not self._stop_event.is_set():
            try:
                self._check_orders()
            except Exception as e:
                logger.exception(f"Error in OrderTimeoutMonitor loop: {e}")
            
            # Sleep with interruptible wait
            self._stop_event.wait(CHECK_INTERVAL)
    
    def _check_orders(self) -> None:
        """Check all tracked orders for timeout or fill status."""
        now = datetime.now()
        orders_to_check = []
        
        with self._lock:
            for order_id, order_info in list(self.tracked_orders.items()):
                # Skip if already processed
                if order_id in self.processed_orders:
                    continue
                
                # Check if timeout reached
                elapsed = (now - order_info["created_at"]).total_seconds()
                if elapsed >= self.timeout_sec:
                    orders_to_check.append((order_id, order_info))
        
        # Process timed-out orders (outside lock to avoid blocking)
        for order_id, order_info in orders_to_check:
            self._handle_timeout(order_id, order_info)
    
    def _handle_timeout(self, order_id: int, order_info: Dict[str, Any]) -> None:
        """
        Handle timed-out order:
        1. Check if filled
        2. If not filled → cancel + place MARKET order
        """
        symbol = order_info["symbol"]
        
        try:
            # Check order status
            order_status = self._get_order_status(symbol, order_id)
            
            if order_status == "FILLED":
                logger.info(f"✅ Order {order_id} ({symbol}) filled before timeout")
                self._mark_processed(order_id)
                return
            
            if order_status in ["CANCELED", "EXPIRED", "REJECTED"]:
                logger.warning(f"⚠️ Order {order_id} ({symbol}) already {order_status}")
                self._mark_processed(order_id)
                return
            
            # Order still open (NEW or PARTIALLY_FILLED) → convert to MARKET
            logger.warning(f"⏰ Order {order_id} ({symbol}) timed out after {self.timeout_sec}s - converting to MARKET")
            
            # Cancel LIMIT order
            cancel_success = self._cancel_order(symbol, order_id)
            if not cancel_success:
                logger.error(f"❌ Failed to cancel order {order_id} ({symbol})")
                # Retry later
                order_info["retries"] += 1
                if order_info["retries"] >= MAX_RETRY_ATTEMPTS:
                    self._mark_processed(order_id)
                return
            
            # Place MARKET order
            market_success = self._place_market_order(order_info)
            if market_success:
                logger.info(f"✅ Successfully converted {order_id} ({symbol}) to MARKET order")
                self._notify_conversion(order_info)
            else:
                logger.error(f"❌ Failed to place MARKET order for {symbol}")
            
            # Mark as processed
            self._mark_processed(order_id)
            
        except Exception as e:
            logger.exception(f"Error handling timeout for order {order_id}: {e}")
            self._mark_processed(order_id)
    
    def _get_order_status(self, symbol: str, order_id: int) -> Optional[str]:
        """Get order status from Binance."""
        try:
            order = self.client.futures_get_order(symbol=symbol, orderId=order_id)
            return order.get("status")
        except Exception as e:
            logger.error(f"Failed to get order status for {order_id}: {e}")
            return None
    
    def _cancel_order(self, symbol: str, order_id: int) -> bool:
        """Cancel LIMIT order."""
        try:
            self.client.futures_cancel_order(symbol=symbol, orderId=order_id)
            logger.info(f"🗑️ Canceled LIMIT order {order_id} ({symbol})")
            return True
        except Exception as e:
            logger.error(f"Failed to cancel order {order_id}: {e}")
            return False
    
    def _place_market_order(self, order_info: Dict[str, Any]) -> bool:
        """Place MARKET order to replace timed-out LIMIT order."""
        try:
            symbol = order_info["symbol"]
            side = order_info["side"]
            quantity = order_info["quantity"]
            order_type = order_info["order_type"]
            position_side = order_info.get("position_side")
            
            # Build order params
            order_params = {
                "symbol": symbol,
                "side": side,
                "type": "MARKET",
                "quantity": quantity,
            }
            
            # Add position side if Hedge Mode
            if position_side:
                order_params["positionSide"] = position_side
            
            # Add reduceOnly for TP/SL (if NOT Hedge Mode)
            if order_type in ["TP", "SL"] and not position_side:
                order_params["reduceOnly"] = True
            
            # Place order
            order = self.client.futures_create_order(**order_params)
            logger.info(f"📤 Placed MARKET order: {symbol} {side} {quantity} (replacing LIMIT)")
            return True
            
        except Exception as e:
            logger.exception(f"Failed to place MARKET order for {order_info['symbol']}: {e}")
            return False
    
    def _notify_conversion(self, order_info: Dict[str, Any]) -> None:
        """Send Telegram notification about LIMIT→MARKET conversion."""
        try:
            from utils.telegram_digest import queue_trade_event
            
            message = (
                f"🔄 **LIMIT→MARKET Conversion**\n"
                f"Symbol: {order_info['symbol']}\n"
                f"Side: {order_info['side']}\n"
                f"Quantity: {order_info['quantity']}\n"
                f"Type: {order_info['order_type']}\n"
                f"Reason: Timeout ({self.timeout_sec}s)"
            )
            
            queue_trade_event("INFO", message)
        except Exception as e:
            logger.warning(f"Failed to send Telegram notification: {e}")
    
    def _mark_processed(self, order_id: int) -> None:
        """Mark order as processed and remove from tracking."""
        with self._lock:
            self.processed_orders.add(order_id)
            if order_id in self.tracked_orders:
                del self.tracked_orders[order_id]


# Global singleton
_monitor_instance: Optional[OrderTimeoutMonitor] = None


def get_timeout_monitor(binance_client=None) -> OrderTimeoutMonitor:
    """Get or create global OrderTimeoutMonitor instance."""
    global _monitor_instance
    
    if _monitor_instance is None:
        if binance_client is None:
            from utils.binance_client import get_futures_client
            binance_client = get_futures_client()
        
        _monitor_instance = OrderTimeoutMonitor(binance_client)
        _monitor_instance.start()
    
    return _monitor_instance
