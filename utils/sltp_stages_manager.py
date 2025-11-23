#!/usr/bin/env python3
# utils/sltp_stages_manager.py
"""
🎯 SL/TP Dynamic Stages Manager (Stage 1-3)
============================================
Implements the 3-stage dynamic SL/TP strategy:
- Stage 1: Move SL to BE+ (break-even + 0.06%) after TP1 hit
- Stage 2: Trailing SL upwards (ATR-based, auto) while locking profit
- Stage 3: Exit at TP2/TP3 or SL (position closed)

Key Features:
- SL never moves DOWN (only UP after BE+)
- Locked profit persists forever (once locked, always above entry)
- Trailing SL auto-updates every price tick
- Compatible with universal_sltp_manager + trailing_sl_state
"""

from __future__ import annotations
import json
import logging
import time
from typing import Dict, Any, Optional, Tuple
from dataclasses import dataclass, asdict

logger = logging.getLogger("sltp_stages")

# Redis prefix for position states
POSITION_STATE_PREFIX = "position:stage:"
STATE_TTL_SECONDS = 86400  # 24 hours

# Stage transition thresholds
BE_PLUS_MULTIPLIER = 1.0006  # entry_price * 1.0006 (0.06% profit lock)
TRAILING_ATR_MULTIPLIER = 1.2  # trail at (current_price - ATR * 1.2)


@dataclass
class PositionStage:
    """Position stage state"""
    symbol: str
    side: str  # LONG/SHORT
    entry_price: float
    atr: float
    
    # Stage tracking
    be_done: bool = False  # True after TP1 hit
    last_trail_high: float = 0.0  # Highest price reached (for trailing)
    
    # SL/TP levels
    current_sl: float = 0.0
    tp1_price: float = 0.0
    tp2_price: float = 0.0
    tp3_price: float = 0.0
    
    # Locked profit (never goes below this)
    locked_profit_price: float = 0.0  # entry_price * BE_PLUS_MULTIPLIER
    
    # Timestamps
    created_at: float = 0.0
    tp1_hit_at: float = 0.0
    last_updated: float = 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dict for JSON serialization"""
        return asdict(self)
    
    @staticmethod
    def from_dict(data: Dict[str, Any]) -> PositionStage:
        """Create from dict"""
        return PositionStage(**data)


class SLTPStagesManager:
    """
    Manages 3-stage SL/TP transitions automatically.
    
    Usage:
        manager = SLTPStagesManager()
        
        # Initialize position after entry
        position = PositionStage(
            symbol="BTCUSDT",
            side="LONG",
            entry_price=50000.0,
            atr=100.0
        )
        manager.init_position(position, sl_initial=49000.0, tp1=52500.0, tp2=55000.0, tp3=58000.0)
        
        # On every tick, update SL if needed
        new_sl = manager.update_sl_if_needed(symbol, current_price=51000.0)
        
        # Check if TP1 was hit (will transition to Stage 1)
        if tp1_hit:
            manager.transition_to_stage1(symbol)
        
        # Cleanup when position closed
        manager.cleanup_position(symbol)
    """
    
    def __init__(self):
        self.redis_available = False
        self._load_redis()
        logger.info(f"🎯 SL/TP Stages Manager initialized | Redis: {'✅' if self.redis_available else '❌ fallback'}")
    
    def _load_redis(self) -> None:
        """Try to load Redis connection"""
        try:
            from utils.redis_client import get_redis
            redis_client = get_redis()
            if redis_client:
                self.redis = redis_client
                self.redis_available = True
        except Exception as e:
            logger.debug(f"Redis unavailable: {e}")
            self.redis = None
    
    def _get_redis_key(self, symbol: str) -> str:
        """Get Redis key for symbol"""
        return f"{POSITION_STATE_PREFIX}{symbol.upper()}"
    
    def _save_position(self, position: PositionStage) -> None:
        """Save position state to Redis"""
        if not self.redis_available:
            return
        
        try:
            key = self._get_redis_key(position.symbol)
            data = json.dumps(position.to_dict())
            self.redis.setex(key, STATE_TTL_SECONDS, data)
            logger.debug(f"💾 Position state saved: {position.symbol}")
        except Exception as e:
            logger.warning(f"Failed to save position: {e}")
    
    def _load_position(self, symbol: str) -> Optional[PositionStage]:
        """Load position state from Redis"""
        if not self.redis_available:
            return None
        
        try:
            key = self._get_redis_key(symbol)
            data = self.redis.get(key)
            if data:
                if isinstance(data, bytes):
                    data = data.decode('utf-8')
                position_dict = json.loads(data)
                return PositionStage.from_dict(position_dict)
        except Exception as e:
            logger.warning(f"Failed to load position: {e}")
        
        return None
    
    def init_position(
        self,
        position: PositionStage,
        sl_initial: float,
        tp1: float,
        tp2: float,
        tp3: float
    ) -> None:
        """
        Initialize position after entry.
        
        Args:
            position: PositionStage object with entry_price, side, symbol, atr
            sl_initial: Initial SL price (swing ± 0.6*ATR)
            tp1, tp2, tp3: TP levels
        """
        position.current_sl = sl_initial
        position.tp1_price = tp1
        position.tp2_price = tp2
        position.tp3_price = tp3
        position.locked_profit_price = position.entry_price * BE_PLUS_MULTIPLIER
        position.last_trail_high = position.entry_price
        position.created_at = time.time()
        position.last_updated = time.time()
        
        self._save_position(position)
        
        logger.info(
            f"📍 Position initialized: {position.symbol} {position.side}\n"
            f"   Entry: {position.entry_price:.8f}\n"
            f"   SL: {sl_initial:.8f}\n"
            f"   TP1/TP2/TP3: {tp1:.8f} / {tp2:.8f} / {tp3:.8f}\n"
            f"   Locked Profit: {position.locked_profit_price:.8f}"
        )
    
    def get_position(self, symbol: str) -> Optional[PositionStage]:
        """Get current position state"""
        return self._load_position(symbol)
    
    def transition_to_stage1(self, symbol: str) -> Tuple[bool, str]:
        """
        Stage 1 Transition: After TP1 hit
        - Set be_done = True
        - Move SL to BE+ (entry * 1.0006)
        - Start trailing SL from this point
        """
        position = self.get_position(symbol)
        if not position:
            return False, f"Position not found: {symbol}"
        
        if position.be_done:
            return False, f"Already in Stage 1: {symbol}"
        
        # Transition
        position.be_done = True
        position.tp1_hit_at = time.time()
        
        # Move SL to BE+
        new_sl = position.entry_price * BE_PLUS_MULTIPLIER
        position.current_sl = new_sl
        position.last_trail_high = max(position.last_trail_high, new_sl)
        
        position.last_updated = time.time()
        self._save_position(position)
        
        logger.info(
            f"🎯 STAGE 1 TRANSITION: {symbol}\n"
            f"   TP1 HIT! Moving SL to BE+\n"
            f"   SL moved to: {new_sl:.8f} ({BE_PLUS_MULTIPLIER*100:.2f}% of entry)\n"
            f"   Profit LOCKED from now on"
        )
        
        return True, f"Transitioned to Stage 1: {symbol}"
    
    def update_sl_if_needed(
        self,
        symbol: str,
        current_price: float
    ) -> Tuple[Optional[float], str]:
        """
        Stage 2 Logic: Continuous SL trailing
        - Only updates if be_done=True (after TP1)
        - SL only moves UP (LONG) or DOWN (SHORT)
        - Never below locked_profit_price
        
        Args:
            symbol: Trading symbol
            current_price: Current market price
        
        Returns:
            (new_sl, reason) or (None, reason) if no update
        """
        position = self.get_position(symbol)
        if not position:
            return None, f"Position not found: {symbol}"
        
        # Only update SL if in Stage 1+ (be_done=True)
        if not position.be_done:
            return None, "Stage 0: TP1 not hit yet, no trailing"
        
        # Calculate new SL using ATR
        if position.side == "LONG":
            # LONG: SL = current_price - (ATR * 1.2)
            new_sl_candidate = current_price - (position.atr * TRAILING_ATR_MULTIPLIER)
            
            # Never go below locked profit
            new_sl = max(new_sl_candidate, position.locked_profit_price)
            
            # Only move UP (tighter)
            if new_sl <= position.current_sl:
                return None, f"SL already tighter ({position.current_sl:.8f})"
        
        else:  # SHORT
            # SHORT: SL = current_price + (ATR * 1.2)
            new_sl_candidate = current_price + (position.atr * TRAILING_ATR_MULTIPLIER)
            
            # Never go below locked profit
            new_sl = min(new_sl_candidate, position.locked_profit_price)
            
            # Only move DOWN (tighter)
            if new_sl >= position.current_sl:
                return None, f"SL already tighter ({position.current_sl:.8f})"
        
        # Update
        old_sl = position.current_sl
        position.current_sl = new_sl
        position.last_trail_high = current_price
        position.last_updated = time.time()
        self._save_position(position)
        
        logger.info(
            f"🔒 STAGE 2 TRAILING: {symbol} {position.side}\n"
            f"   Current price: {current_price:.8f}\n"
            f"   SL trailed: {old_sl:.8f} → {new_sl:.8f}\n"
            f"   Profit locked: {position.locked_profit_price:.8f}"
        )
        
        return new_sl, f"SL trailed: {old_sl:.8f} → {new_sl:.8f}"
    
    def check_stage3_exit(
        self,
        symbol: str,
        current_price: float
    ) -> Tuple[str, Optional[Dict[str, Any]]]:
        """
        Stage 3 Logic: Check if exit conditions met
        - Check if TP2/TP3 hit → CLOSE
        - Check if SL hit → CLOSE
        
        Returns:
            (status, details)
            status: "close_tp", "close_sl", or "holding"
            details: exit info or None
        """
        position = self.get_position(symbol)
        if not position:
            return "error", None
        
        # Check TP hits
        if position.side == "LONG":
            if current_price >= position.tp3_price:
                return "close_tp3", {
                    "symbol": symbol,
                    "exit_price": current_price,
                    "tp_level": 3,
                    "profit_at_entry": position.locked_profit_price - position.entry_price
                }
            if current_price >= position.tp2_price:
                return "close_tp2", {
                    "symbol": symbol,
                    "exit_price": current_price,
                    "tp_level": 2,
                    "profit_at_entry": position.locked_profit_price - position.entry_price
                }
            if current_price <= position.current_sl:
                return "close_sl", {
                    "symbol": symbol,
                    "exit_price": current_price,
                    "sl_level": position.current_sl,
                    "profit_locked": position.locked_profit_price - position.entry_price
                }
        
        else:  # SHORT
            if current_price <= position.tp3_price:
                return "close_tp3", {
                    "symbol": symbol,
                    "exit_price": current_price,
                    "tp_level": 3,
                    "profit_at_entry": position.entry_price - position.locked_profit_price
                }
            if current_price <= position.tp2_price:
                return "close_tp2", {
                    "symbol": symbol,
                    "exit_price": current_price,
                    "tp_level": 2,
                    "profit_at_entry": position.entry_price - position.locked_profit_price
                }
            if current_price >= position.current_sl:
                return "close_sl", {
                    "symbol": symbol,
                    "exit_price": current_price,
                    "sl_level": position.current_sl,
                    "profit_locked": position.entry_price - position.locked_profit_price
                }
        
        return "holding", None
    
    def cleanup_position(self, symbol: str) -> None:
        """
        Stage 3 Final: Cleanup after position closed
        - Remove from Redis
        - Update metrics (locked_profit, SL_saves, etc)
        """
        position = self.get_position(symbol)
        if not position:
            return
        
        # Calculate metrics
        if position.side == "LONG":
            locked_profit = position.locked_profit_price - position.entry_price
        else:
            locked_profit = position.entry_price - position.locked_profit_price
        
        logger.info(
            f"🧹 Position closed: {symbol}\n"
            f"   Locked profit: {locked_profit:.8f}\n"
            f"   Final SL: {position.current_sl:.8f}\n"
            f"   Duration: {time.time() - position.created_at:.1f}s"
        )
        
        # Delete from Redis
        if self.redis_available:
            try:
                key = self._get_redis_key(symbol)
                self.redis.delete(key)
            except Exception as e:
                logger.warning(f"Failed to delete position from Redis: {e}")


# Singleton instance
_manager: Optional[SLTPStagesManager] = None


def get_sltp_stages_manager() -> SLTPStagesManager:
    """Get or create singleton instance"""
    global _manager
    if _manager is None:
        _manager = SLTPStagesManager()
    return _manager


__all__ = ["SLTPStagesManager", "PositionStage", "get_sltp_stages_manager"]
