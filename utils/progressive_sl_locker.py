#!/usr/bin/env python3
# utils/progressive_sl_locker.py
"""
Progressive SL Locker - Locks profits at each TP level
=======================================================
Tracks which TP levels have been hit and progressively moves SL up.
When TP1 is hit -> move SL to TP1
When TP2 is hit -> move SL to TP2
When TP3 is hit -> move SL to TP3
"""

import os
import time
import json
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger("progressive_sl_locker")

# Redis client
try:
    from utils.redis_client import get_redis
    REDIS_AVAILABLE = True
except Exception as e:
    logger.warning(f"Redis unavailable: {e}")
    REDIS_AVAILABLE = False
    get_redis = None  # type: ignore

REDIS_KEY_PREFIX = "progressive_sl:"
_tp_state_cache: Dict[str, Dict[str, Any]] = {}


class ProgressiveSLLocker:
    """Tracks TP hits and locks SL progressively at each level"""
    
    def __init__(self):
        self.redis_available = REDIS_AVAILABLE
        logger.info(f"Progressive SL Locker initialized | Redis: {'✅' if REDIS_AVAILABLE else '❌'}")
    
    def _get_redis_key(self, symbol: str) -> str:
        return f"{REDIS_KEY_PREFIX}{symbol}"
    
    def _load_from_redis(self, symbol: str) -> Optional[Dict[str, Any]]:
        if not self.redis_available or not get_redis:
            return None
        try:
            redis_client = get_redis()
            if not redis_client:
                return None
            key = self._get_redis_key(symbol)
            data = redis_client.get(key)
            if data:
                return json.loads(data)
            return None
        except Exception as e:
            logger.debug(f"Failed to load from Redis for {symbol}: {e}")
            return None
    
    def _save_to_redis(self, symbol: str, state: Dict[str, Any]) -> None:
        if not self.redis_available or not get_redis:
            return
        try:
            redis_client = get_redis()
            if not redis_client:
                return
            key = self._get_redis_key(symbol)
            redis_client.setex(key, 3600, json.dumps(state))
        except Exception as e:
            logger.debug(f"Failed to save to Redis for {symbol}: {e}")
    
    def init_tp_tracking(self, symbol: str, tp1: float, tp2: float, tp3: float) -> None:
        """Initialize TP tracking for a symbol"""
        state = {
            "symbol": symbol,
            "tp1": tp1,
            "tp2": tp2,
            "tp3": tp3,
            "tp1_hit": False,
            "tp2_hit": False,
            "tp3_hit": False,
            "locked_sl_at": None,  # "TP1", "TP2", or "TP3"
            "initialized_at": time.time()
        }
        _tp_state_cache[symbol] = state
        self._save_to_redis(symbol, state)
        logger.info(f"🎯 Progressive SL initialized for {symbol}: TP1={tp1:.8f}, TP2={tp2:.8f}, TP3={tp3:.8f}")
    
    def get_next_sl_lock_level(self, symbol: str, current_price: float, side: str) -> Optional[tuple[str, float]]:
        """
        Determine if SL should move to next TP level
        Returns: (tp_level, new_sl_price) or None if no update needed
        """
        state = self._load_from_redis(symbol)
        if state is None:
            state = _tp_state_cache.get(symbol)
        
        if state is None:
            return None
        
        tp1 = state.get("tp1", 0)
        tp2 = state.get("tp2", 0)
        tp3 = state.get("tp3", 0)
        locked_at = state.get("locked_sl_at")
        
        # LONG: price moves up, TP goes up, SL follows
        if side == "LONG":
            # Check TP3 first (highest priority)
            if not state.get("tp3_hit") and current_price >= tp3:
                logger.info(f"🎯 {symbol} LONG: TP3 HIT @ {current_price:.8f} - Locking SL at TP3 ({tp3:.8f})")
                state["tp3_hit"] = True
                state["locked_sl_at"] = "TP3"
                _tp_state_cache[symbol] = state
                self._save_to_redis(symbol, state)
                return ("TP3", tp3)
            
            # Check TP2
            if not state.get("tp2_hit") and current_price >= tp2:
                logger.info(f"🎯 {symbol} LONG: TP2 HIT @ {current_price:.8f} - Locking SL at TP2 ({tp2:.8f})")
                state["tp2_hit"] = True
                state["locked_sl_at"] = "TP2"
                _tp_state_cache[symbol] = state
                self._save_to_redis(symbol, state)
                return ("TP2", tp2)
            
            # Check TP1
            if not state.get("tp1_hit") and current_price >= tp1:
                logger.info(f"🎯 {symbol} LONG: TP1 HIT @ {current_price:.8f} - Locking SL at TP1 ({tp1:.8f})")
                state["tp1_hit"] = True
                state["locked_sl_at"] = "TP1"
                _tp_state_cache[symbol] = state
                self._save_to_redis(symbol, state)
                return ("TP1", tp1)
        
        # SHORT: price moves down, TP goes down, SL follows
        else:  # SHORT
            # Check TP3 first (lowest price)
            if not state.get("tp3_hit") and current_price <= tp3:
                logger.info(f"🎯 {symbol} SHORT: TP3 HIT @ {current_price:.8f} - Locking SL at TP3 ({tp3:.8f})")
                state["tp3_hit"] = True
                state["locked_sl_at"] = "TP3"
                _tp_state_cache[symbol] = state
                self._save_to_redis(symbol, state)
                return ("TP3", tp3)
            
            # Check TP2
            if not state.get("tp2_hit") and current_price <= tp2:
                logger.info(f"🎯 {symbol} SHORT: TP2 HIT @ {current_price:.8f} - Locking SL at TP2 ({tp2:.8f})")
                state["tp2_hit"] = True
                state["locked_sl_at"] = "TP2"
                _tp_state_cache[symbol] = state
                self._save_to_redis(symbol, state)
                return ("TP2", tp2)
            
            # Check TP1
            if not state.get("tp1_hit") and current_price <= tp1:
                logger.info(f"🎯 {symbol} SHORT: TP1 HIT @ {current_price:.8f} - Locking SL at TP1 ({tp1:.8f})")
                state["tp1_hit"] = True
                state["locked_sl_at"] = "TP1"
                _tp_state_cache[symbol] = state
                self._save_to_redis(symbol, state)
                return ("TP1", tp1)
        
        return None
    
    def cleanup_symbol(self, symbol: str) -> None:
        """Cleanup state when position closes"""
        if symbol in _tp_state_cache:
            del _tp_state_cache[symbol]
        
        if self.redis_available and get_redis:
            try:
                redis_client = get_redis()
                if redis_client:
                    key = self._get_redis_key(symbol)
                    redis_client.delete(key)
                    logger.debug(f"Cleaned up progressive SL state for {symbol}")
            except Exception as e:
                logger.debug(f"Failed to cleanup Redis for {symbol}: {e}")


_locker: Optional[ProgressiveSLLocker] = None


def get_progressive_sl_locker() -> ProgressiveSLLocker:
    global _locker
    if _locker is None:
        _locker = ProgressiveSLLocker()
    return _locker


__all__ = ["ProgressiveSLLocker", "get_progressive_sl_locker"]
