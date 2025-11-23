#!/usr/bin/env python3
# utils/kpi_tracker.py
"""
KPI Tracker - Priority 3 Features
==================================
Tracks:
- Auto-Switch Counter
- SL-Saves (positions saved by SL management)
- Missed Trades (proposals not executed)
- Locked Profit (cumulative from stages)
"""

from __future__ import annotations
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List
import os
import logging

logger = logging.getLogger("algogpt.kpi_tracker")

# Redis for fast KPI tracking
try:
    import redis.asyncio as aioredis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False

REDIS_URL = os.getenv("REDIS_URL") or os.getenv("VALKEY_URL") or ""
NAMESPACE = os.getenv("REDIS_NAMESPACE", "algogpt")


class KPITracker:
    """Real-time KPI tracking system"""
    
    def __init__(self):
        self.redis = None
        self.prefix = f"{NAMESPACE}:kpi"
    
    async def init(self):
        """Initialize Redis connection"""
        if not REDIS_AVAILABLE or not REDIS_URL:
            logger.warning("Redis not available for KPI tracking")
            return
        
        try:
            self.redis = aioredis.from_url(REDIS_URL, decode_responses=True)
            logger.info("✅ KPI Tracker initialized")
        except Exception as e:
            logger.error(f"Failed to initialize KPI Tracker: {e}")
    
    async def close(self):
        """Close Redis connection"""
        if self.redis:
            await self.redis.close()
    
    # ============================================================================
    # Auto-Switch Counter
    # ============================================================================
    
    async def increment_auto_switch(self, user_id: str, from_user: str = ""):
        """Track admin user switch"""
        if not self.redis:
            return
        
        key = f"{self.prefix}:auto_switch:daily:{datetime.utcnow().strftime('%Y-%m-%d')}"
        counter_key = f"{self.prefix}:auto_switch:counter:{user_id}"
        
        try:
            # Increment daily counter
            await self.redis.hincrby(key, user_id, 1)
            
            # Increment total counter
            await self.redis.incr(counter_key)
            
            # Store last switch time
            await self.redis.hset(
                f"{self.prefix}:auto_switch:last",
                user_id,
                f"{from_user}→{user_id}|{datetime.utcnow().isoformat()}"
            )
            
            logger.info(f"📊 Auto-Switch tracked: {from_user}→{user_id}")
        except Exception as e:
            logger.error(f"Failed to track auto-switch: {e}")
    
    async def get_auto_switch_count(self, user_id: str, period: str = "day") -> int:
        """Get auto-switch count for user"""
        if not self.redis:
            return 0
        
        try:
            if period == "day":
                key = f"{self.prefix}:auto_switch:daily:{datetime.utcnow().strftime('%Y-%m-%d')}"
                count = await self.redis.hget(key, user_id)
            else:  # total
                key = f"{self.prefix}:auto_switch:counter:{user_id}"
                count = await self.redis.get(key)
            
            return int(count or 0)
        except Exception as e:
            logger.error(f"Failed to get auto-switch count: {e}")
            return 0
    
    # ============================================================================
    # SL-Saves Tracker
    # ============================================================================
    
    async def increment_sl_save(self, user_id: str, symbol: str, saved_amount: float = 0.0):
        """Track SL save (position saved by SL management)"""
        if not self.redis:
            return
        
        key = f"{self.prefix}:sl_saves:daily:{datetime.utcnow().strftime('%Y-%m-%d')}"
        counter_key = f"{self.prefix}:sl_saves:counter:{user_id}"
        profit_key = f"{self.prefix}:sl_saves:profit:{user_id}"
        
        try:
            # Increment daily SL saves
            await self.redis.hincrby(key, user_id, 1)
            
            # Increment total SL saves
            await self.redis.incr(counter_key)
            
            # Add saved profit
            if saved_amount > 0:
                await self.redis.incrbyfloat(profit_key, saved_amount)
            
            # Track by symbol
            symbol_key = f"{self.prefix}:sl_saves:symbol:{symbol}"
            await self.redis.hincrby(symbol_key, user_id, 1)
            
            logger.info(f"💰 SL-Save tracked: {symbol} (Saved: ${saved_amount:.2f})")
        except Exception as e:
            logger.error(f"Failed to track SL-save: {e}")
    
    async def get_sl_saves(self, user_id: str, period: str = "day") -> Dict[str, Any]:
        """Get SL-saves statistics"""
        if not self.redis:
            return {"count": 0, "profit": 0.0}
        
        try:
            if period == "day":
                key = f"{self.prefix}:sl_saves:daily:{datetime.utcnow().strftime('%Y-%m-%d')}"
                count = await self.redis.hget(key, user_id)
            else:  # total
                key = f"{self.prefix}:sl_saves:counter:{user_id}"
                count = await self.redis.get(key)
            
            profit_key = f"{self.prefix}:sl_saves:profit:{user_id}"
            profit = await self.redis.get(profit_key)
            
            return {
                "count": int(count or 0),
                "profit": float(profit or 0.0)
            }
        except Exception as e:
            logger.error(f"Failed to get SL-saves: {e}")
            return {"count": 0, "profit": 0.0}
    
    # ============================================================================
    # Missed Trades Logger
    # ============================================================================
    
    async def log_missed_trade(self, user_id: str, symbol: str, reason: str = "unknown", entry: float = 0.0):
        """Log trade proposal that wasn't executed"""
        if not self.redis:
            return
        
        key = f"{self.prefix}:missed_trades:daily:{datetime.utcnow().strftime('%Y-%m-%d')}"
        counter_key = f"{self.prefix}:missed_trades:counter:{user_id}"
        reasons_key = f"{self.prefix}:missed_trades:reasons"
        
        try:
            # Increment daily missed trades
            await self.redis.hincrby(key, user_id, 1)
            
            # Increment total missed trades
            await self.redis.incr(counter_key)
            
            # Track reason
            await self.redis.hincrby(reasons_key, reason, 1)
            
            # Store missed trade details
            missed_key = f"{self.prefix}:missed_trades:details:{user_id}"
            await self.redis.lpush(
                missed_key,
                f"{symbol}|{reason}|{entry}|{datetime.utcnow().isoformat()}"
            )
            
            # Keep only last 100 missed trades
            await self.redis.ltrim(missed_key, 0, 99)
            
            logger.info(f"⚠️ Missed Trade logged: {symbol} ({reason})")
        except Exception as e:
            logger.error(f"Failed to log missed trade: {e}")
    
    async def get_missed_trades(self, user_id: str, period: str = "day", limit: int = 50) -> Dict[str, Any]:
        """Get missed trades data"""
        if not self.redis:
            return {"count": 0, "details": [], "reasons": {}}
        
        try:
            # Get count
            if period == "day":
                key = f"{self.prefix}:missed_trades:daily:{datetime.utcnow().strftime('%Y-%m-%d')}"
                count = await self.redis.hget(key, user_id)
            else:  # total
                key = f"{self.prefix}:missed_trades:counter:{user_id}"
                count = await self.redis.get(key)
            
            # Get details
            missed_key = f"{self.prefix}:missed_trades:details:{user_id}"
            details = await self.redis.lrange(missed_key, 0, limit - 1)
            
            # Parse details
            parsed_details = []
            for detail in details:
                parts = detail.split("|")
                if len(parts) >= 4:
                    parsed_details.append({
                        "symbol": parts[0],
                        "reason": parts[1],
                        "entry": float(parts[2]) if parts[2] else 0.0,
                        "timestamp": parts[3]
                    })
            
            # Get reasons
            reasons_key = f"{self.prefix}:missed_trades:reasons"
            reasons = await self.redis.hgetall(reasons_key) if self.redis else {}
            
            return {
                "count": int(count or 0),
                "details": parsed_details,
                "reasons": {k: int(v) for k, v in reasons.items()}
            }
        except Exception as e:
            logger.error(f"Failed to get missed trades: {e}")
            return {"count": 0, "details": [], "reasons": {}}
    
    # ============================================================================
    # Locked Profit Tracker
    # ============================================================================
    
    async def add_locked_profit(self, user_id: str, symbol: str, amount: float, stage: int = 0):
        """Track locked profit from SL/TP stages"""
        if not self.redis:
            return
        
        key = f"{self.prefix}:locked_profit:daily:{datetime.utcnow().strftime('%Y-%m-%d')}"
        total_key = f"{self.prefix}:locked_profit:total:{user_id}"
        symbol_key = f"{self.prefix}:locked_profit:symbol:{symbol}"
        
        try:
            # Add to daily locked profit
            await self.redis.hincrbyfloat(key, user_id, amount)
            
            # Add to total locked profit
            await self.redis.incrbyfloat(total_key, amount)
            
            # Track by symbol
            await self.redis.hincrbyfloat(symbol_key, user_id, amount)
            
            # Store locked profit event
            events_key = f"{self.prefix}:locked_profit:events:{user_id}"
            await self.redis.lpush(
                events_key,
                f"{symbol}|{amount}|Stage{stage}|{datetime.utcnow().isoformat()}"
            )
            
            # Keep last 100 events
            await self.redis.ltrim(events_key, 0, 99)
            
            logger.info(f"🔒 Locked Profit: {symbol} +${amount:.2f} (Stage {stage})")
        except Exception as e:
            logger.error(f"Failed to track locked profit: {e}")
    
    async def get_locked_profit(self, user_id: str, period: str = "day") -> Dict[str, Any]:
        """Get locked profit statistics"""
        if not self.redis:
            return {"daily": 0.0, "total": 0.0}
        
        try:
            if period == "day":
                key = f"{self.prefix}:locked_profit:daily:{datetime.utcnow().strftime('%Y-%m-%d')}"
                amount = await self.redis.hget(key, user_id)
                return {
                    "daily": float(amount or 0.0),
                    "total": None
                }
            else:  # total
                key = f"{self.prefix}:locked_profit:total:{user_id}"
                amount = await self.redis.get(key)
                return {
                    "daily": None,
                    "total": float(amount or 0.0)
                }
        except Exception as e:
            logger.error(f"Failed to get locked profit: {e}")
            return {"daily": 0.0, "total": 0.0}
    
    async def get_locked_profit_events(self, user_id: str, limit: int = 50) -> List[Dict[str, Any]]:
        """Get locked profit events"""
        if not self.redis:
            return []
        
        try:
            events_key = f"{self.prefix}:locked_profit:events:{user_id}"
            events = await self.redis.lrange(events_key, 0, limit - 1)
            
            parsed = []
            for event in events:
                parts = event.split("|")
                if len(parts) >= 4:
                    parsed.append({
                        "symbol": parts[0],
                        "amount": float(parts[1]),
                        "stage": parts[2],
                        "timestamp": parts[3]
                    })
            
            return parsed
        except Exception as e:
            logger.error(f"Failed to get locked profit events: {e}")
            return []
    
    # ============================================================================
    # Dashboard Summary
    # ============================================================================
    
    async def get_kpi_summary(self, user_id: str) -> Dict[str, Any]:
        """Get complete KPI summary for dashboard"""
        try:
            auto_switches = await self.get_auto_switch_count(user_id, "day")
            sl_saves = await self.get_sl_saves(user_id, "day")
            missed_trades = await self.get_missed_trades(user_id, "day")
            locked_profit = await self.get_locked_profit(user_id, "day")
            
            return {
                "timestamp": datetime.utcnow().isoformat(),
                "auto_switch_count": auto_switches,
                "sl_saves": sl_saves,
                "missed_trades_count": missed_trades["count"],
                "locked_profit_daily": locked_profit["daily"],
                "summary": {
                    "title": "📊 Daily KPI Summary",
                    "auto_switch": f"🔄 {auto_switches} switches",
                    "sl_saves": f"💰 {sl_saves['count']} saves (${sl_saves['profit']:.2f})",
                    "missed_trades": f"⚠️ {missed_trades['count']} missed",
                    "locked_profit": f"🔒 ${locked_profit['daily']:.2f} locked"
                }
            }
        except Exception as e:
            logger.error(f"Failed to get KPI summary: {e}")
            return {
                "timestamp": datetime.utcnow().isoformat(),
                "auto_switch_count": 0,
                "sl_saves": {"count": 0, "profit": 0.0},
                "missed_trades_count": 0,
                "locked_profit_daily": 0.0,
                "summary": {}
            }


# Global tracker instance
_tracker: Optional[KPITracker] = None


async def get_tracker() -> KPITracker:
    """Get global KPI tracker instance"""
    global _tracker
    if _tracker is None:
        _tracker = KPITracker()
        await _tracker.init()
    return _tracker
