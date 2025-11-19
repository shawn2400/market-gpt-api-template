#!/usr/bin/env python3
# utils/trailing_sl_state.py
"""
Trailing SL State Manager - Redis-Backed Position Tracking
===========================================================
Tracks current SL price for each symbol to enable true trailing stops.

Features:
- Redis-backed persistence (survives restarts)
- Prevents SL from moving backwards (LONG: only up, SHORT: only down)
- Auto-cleanup on position close
- Fallback to memory if Redis unavailable

Author: AlgoGPT Team
"""

import os
import time
import json
import logging
from typing import Dict, Any, Optional, Tuple

logger = logging.getLogger("trailing_sl_state")

# Redis client
try:
    from utils.redis_client import get_redis
    REDIS_AVAILABLE = True
except Exception as e:
    logger.warning(f"Redis unavailable: {e}")
    REDIS_AVAILABLE = False
    get_redis = None  # type: ignore

# Configuration
REDIS_KEY_PREFIX = "trailing_sl:"
STATE_TTL_SECONDS = 3600  # 1 hour auto-cleanup

# In-memory fallback cache
_trailing_sl_cache: Dict[str, Dict[str, Any]] = {}


class TrailingSLStateManager:
    """
    Manages trailing SL state to prevent backwards movement.
    
    Usage:
        manager = TrailingSLStateManager()
        
        # Get current SL (or None if not set)
        current_sl = manager.get_current_sl(symbol, side)
        
        # Update SL (only if new SL is better)
        success = manager.update_sl(symbol, side, new_sl_price, entry_price)
        
        # Cleanup on position close
        manager.cleanup_symbol(symbol)
    """
    
    def __init__(self):
        self.redis_available = REDIS_AVAILABLE
        
        logger.info(
            f"🎯 Trailing SL State Manager initialized | "
            f"Redis: {'✅' if self.redis_available else '❌ fallback to memory'}"
        )
    
    def _get_redis_key(self, symbol: str) -> str:
        """Generate Redis key for symbol"""
        return f"{REDIS_KEY_PREFIX}{symbol}"
    
    def _load_from_redis(self, symbol: str) -> Optional[Dict[str, Any]]:
        """
        Load trailing SL state from Redis
        
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
                logger.debug(f"💾 Loaded SL state from Redis: {symbol}")
                return state
            
            return None
            
        except Exception as e:
            logger.warning(f"💾 Failed to load from Redis for {symbol}: {e}")
            return None
    
    def _save_to_redis(self, symbol: str, state: Dict[str, Any]) -> None:
        """
        Save trailing SL state to Redis
        
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
            logger.debug(f"💾 Saved SL state to Redis: {symbol}")
            
        except Exception as e:
            logger.warning(f"💾 Failed to save to Redis for {symbol}: {e}")
    
    def get_current_sl(
        self, 
        symbol: str,
        side: str
    ) -> Optional[float]:
        """
        Get current SL price for symbol
        
        Args:
            symbol: Trading symbol
            side: LONG or SHORT
            
        Returns:
            Current SL price or None if not set
        """
        # Try Redis first, fallback to memory
        state = self._load_from_redis(symbol)
        if state is None:
            state = _trailing_sl_cache.get(symbol)
        
        if state is None:
            return None
        
        # Validate side matches
        if state.get("side") != side:
            logger.warning(
                f"⚠️ {symbol}: SL state side mismatch "
                f"(stored={state.get('side')}, requested={side})"
            )
            return None
        
        return state.get("current_sl")
    
    def update_sl(
        self,
        symbol: str,
        side: str,
        new_sl: float,
        entry_price: float
    ) -> Tuple[bool, str]:
        """
        Update SL price (only if new SL is better - prevents backwards movement)
        
        Args:
            symbol: Trading symbol
            side: LONG or SHORT
            new_sl: Proposed new SL price
            entry_price: Position entry price (for validation)
            
        Returns:
            (success, reason)
            success: True if SL was updated
            reason: Explanation
        """
        # Get current SL
        current_sl = self.get_current_sl(symbol, side)
        
        # If no current SL, set it (first time)
        if current_sl is None:
            state = {
                "symbol": symbol,
                "side": side,
                "current_sl": new_sl,
                "entry_price": entry_price,
                "last_updated": time.time(),
                "update_count": 1
            }
            
            # Save to both Redis and memory
            _trailing_sl_cache[symbol] = state
            self._save_to_redis(symbol, state)
            
            logger.info(f"🎯 {symbol}: Initial trailing SL set @ {new_sl:.8f}")
            return (True, "Initial SL set")
        
        # Validate: SL can only move in favorable direction
        if side == "LONG":
            # LONG: SL can only move UP (higher price = tighter stop)
            if new_sl <= current_sl:
                logger.debug(
                    f"⏸️ {symbol} LONG: New SL {new_sl:.8f} not better than "
                    f"current {current_sl:.8f}, skipping"
                )
                return (False, f"New SL {new_sl:.8f} <= current {current_sl:.8f}")
        else:  # SHORT
            # SHORT: SL can only move DOWN (lower price = tighter stop)
            if new_sl >= current_sl:
                logger.debug(
                    f"⏸️ {symbol} SHORT: New SL {new_sl:.8f} not better than "
                    f"current {current_sl:.8f}, skipping"
                )
                return (False, f"New SL {new_sl:.8f} >= current {current_sl:.8f}")
        
        # Update SL
        state = {
            "symbol": symbol,
            "side": side,
            "current_sl": new_sl,
            "previous_sl": current_sl,
            "entry_price": entry_price,
            "last_updated": time.time(),
            "update_count": _trailing_sl_cache.get(symbol, {}).get("update_count", 0) + 1
        }
        
        # Save to both Redis and memory
        _trailing_sl_cache[symbol] = state
        self._save_to_redis(symbol, state)
        
        sl_change_pct = abs((new_sl - current_sl) / current_sl) * 100
        logger.info(
            f"📈 {symbol} {side}: Trailing SL updated: "
            f"{current_sl:.8f} → {new_sl:.8f} ({sl_change_pct:+.2f}%)"
        )
        
        return (True, f"SL updated: {current_sl:.8f} → {new_sl:.8f}")
    
    def cleanup_symbol(self, symbol: str) -> None:
        """
        Cleanup state for closed position
        
        Args:
            symbol: Trading symbol
        """
        # Remove from memory
        if symbol in _trailing_sl_cache:
            del _trailing_sl_cache[symbol]
        
        # Remove from Redis
        if self.redis_available and get_redis:
            try:
                redis_client = get_redis()
                if redis_client:
                    key = self._get_redis_key(symbol)
                    redis_client.delete(key)
                    logger.debug(f"💾 Removed {symbol} trailing SL state from Redis")
            except Exception as e:
                logger.warning(f"💾 Failed to cleanup Redis for {symbol}: {e}")
        
        logger.debug(f"🧹 Cleaned up trailing SL state for {symbol}")
    
    def get_state_summary(self) -> Dict[str, Any]:
        """Get summary of current state"""
        return {
            "tracked_symbols": len(_trailing_sl_cache),
            "redis_available": self.redis_available,
            "symbols": list(_trailing_sl_cache.keys())
        }


# Singleton instance
_state_manager: Optional[TrailingSLStateManager] = None


def get_trailing_sl_state_manager() -> TrailingSLStateManager:
    """Get or create singleton state manager instance"""
    global _state_manager
    if _state_manager is None:
        _state_manager = TrailingSLStateManager()
    return _state_manager


__all__ = ["TrailingSLStateManager", "get_trailing_sl_state_manager"]
