#!/usr/bin/env python3
# utils/breakeven_state.py
"""
Breakeven State Manager - Prevent Duplicate Telegram Notifications
===================================================================

Tracks last sent breakeven price per symbol using Redis persistence.
Only sends Telegram alerts when SL price actually changes.

Features:
- Redis-backed state tracking
- Prevents duplicate notifications
- Auto-cleanup after position closure
- Survives worker restarts

Author: AlgoGPT Team
"""

import os
import time
import json
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger("breakeven_state")

# Redis client
try:
    from utils.redis_client import get_redis
    REDIS_AVAILABLE = True
except Exception as e:
    logger.warning(f"Redis unavailable: {e}")
    REDIS_AVAILABLE = False
    get_redis = None  # type: ignore

# Configuration
REDIS_KEY_PREFIX = "breakeven:state:"
STATE_TTL_SECONDS = 3600  # 1 hour auto-cleanup
NOTIFICATION_COOLDOWN_SEC = 300  # 5 minutes minimum between same alerts

# In-memory fallback cache
_breakeven_cache: Dict[str, Dict[str, Any]] = {}


class BreakevenStateManager:
    """
    Manages breakeven notification state to prevent duplicates
    
    Usage:
        manager = BreakevenStateManager()
        
        # Check if should send notification
        if manager.should_send_notification(symbol, be_price):
            send_telegram_message(...)
            manager.mark_sent(symbol, be_price)
    """
    
    def __init__(self):
        self.cooldown_sec = NOTIFICATION_COOLDOWN_SEC
        self.redis_available = REDIS_AVAILABLE
        
        logger.info(
            f"🧠 Breakeven State Manager initialized | "
            f"Cooldown: {self.cooldown_sec}s | "
            f"Redis: {'✅' if self.redis_available else '❌ fallback to memory'}"
        )
    
    def _get_redis_key(self, symbol: str) -> str:
        """Generate Redis key for symbol"""
        return f"{REDIS_KEY_PREFIX}{symbol}"
    
    def _load_from_redis(self, symbol: str) -> Optional[Dict[str, Any]]:
        """
        Load breakeven state from Redis
        
        Args:
            symbol: Trading symbol
            
        Returns:
            State dict or None if not found
        """
        if not self.redis_available or not get_redis:
            return None
        
        try:
            redis_client = get_redis()
            if not redis_client:
                return None
            
            key = self._get_redis_key(symbol)
            data = redis_client.get(key)
            
            if data:
                state = json.loads(data)
                logger.debug(f"💾 Loaded state from Redis: {symbol}")
                return state
            
            return None
            
        except Exception as e:
            logger.warning(f"💾 Failed to load from Redis for {symbol}: {e}")
            return None
    
    def _save_to_redis(self, symbol: str, state: Dict[str, Any]) -> None:
        """
        Save breakeven state to Redis
        
        Args:
            symbol: Trading symbol
            state: State dict to save
        """
        if not self.redis_available or not get_redis:
            return
        
        try:
            redis_client = get_redis()
            if not redis_client:
                return
            
            key = self._get_redis_key(symbol)
            
            # Save with TTL (auto-cleanup after 1 hour)
            redis_client.setex(key, STATE_TTL_SECONDS, json.dumps(state))
            logger.debug(f"💾 Saved state to Redis: {symbol}")
            
        except Exception as e:
            logger.warning(f"💾 Failed to save to Redis for {symbol}: {e}")
    
    def should_send_notification(
        self, 
        symbol: str, 
        current_be_price: float
    ) -> bool:
        """
        Check if should send breakeven notification
        
        Returns False if:
        - Same price was already sent recently
        - Still within cooldown period
        
        Args:
            symbol: Trading symbol
            current_be_price: Current breakeven price
            
        Returns:
            True if notification should be sent
        """
        # Try Redis first, fallback to memory
        state = self._load_from_redis(symbol)
        if state is None:
            state = _breakeven_cache.get(symbol)
        
        if state is None:
            # No previous state - OK to send
            logger.debug(f"🆕 {symbol}: No previous breakeven state, OK to send")
            return True
        
        last_price = state.get("be_price", 0.0)
        last_sent_time = state.get("timestamp", 0.0)
        current_time = time.time()
        
        # Check if price changed (allow 0.01% tolerance)
        price_diff_pct = abs(current_be_price - last_price) / last_price if last_price > 0 else 1.0
        
        if price_diff_pct < 0.0001:  # Same price (within 0.01%)
            time_since_last = current_time - last_sent_time
            
            if time_since_last < self.cooldown_sec:
                logger.debug(
                    f"🔇 {symbol}: Same price {current_be_price:.8f}, "
                    f"cooldown active ({time_since_last:.0f}s / {self.cooldown_sec}s)"
                )
                return False
            else:
                # Cooldown expired - can resend (for reminder)
                logger.info(
                    f"🔔 {symbol}: Cooldown expired, resending breakeven reminder"
                )
                return True
        else:
            # Price changed - definitely send
            logger.info(
                f"📈 {symbol}: Breakeven price changed: "
                f"{last_price:.8f} → {current_be_price:.8f} "
                f"({price_diff_pct*100:.2f}%)"
            )
            return True
    
    def mark_sent(
        self, 
        symbol: str, 
        be_price: float
    ) -> None:
        """
        Mark breakeven notification as sent
        
        Args:
            symbol: Trading symbol
            be_price: Breakeven price that was sent
        """
        state = {
            "symbol": symbol,
            "be_price": be_price,
            "timestamp": time.time(),
            "sent_count": 1
        }
        
        # Save to both Redis and memory
        _breakeven_cache[symbol] = state
        self._save_to_redis(symbol, state)
        
        logger.debug(f"✅ {symbol}: Marked breakeven notification as sent @ {be_price:.8f}")
    
    def cleanup_symbol(self, symbol: str) -> None:
        """
        Cleanup state for closed position
        
        Args:
            symbol: Trading symbol
        """
        # Remove from memory
        if symbol in _breakeven_cache:
            del _breakeven_cache[symbol]
        
        # Remove from Redis
        if self.redis_available and get_redis:
            try:
                redis_client = get_redis()
                if redis_client:
                    key = self._get_redis_key(symbol)
                    redis_client.delete(key)
                    logger.debug(f"💾 Removed {symbol} breakeven state from Redis")
            except Exception as e:
                logger.warning(f"💾 Failed to cleanup Redis for {symbol}: {e}")
        
        logger.debug(f"🧹 Cleaned up breakeven state for {symbol}")
    
    def get_state_summary(self) -> Dict[str, Any]:
        """Get summary of current state"""
        return {
            "tracked_symbols": len(_breakeven_cache),
            "cooldown_sec": self.cooldown_sec,
            "redis_available": self.redis_available,
            "symbols": list(_breakeven_cache.keys())
        }


# Singleton instance
_state_manager: Optional[BreakevenStateManager] = None


def get_breakeven_state_manager() -> BreakevenStateManager:
    """Get or create singleton state manager instance"""
    global _state_manager
    if _state_manager is None:
        _state_manager = BreakevenStateManager()
    return _state_manager
