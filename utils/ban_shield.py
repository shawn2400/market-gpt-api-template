"""
🛡️ Auto-Ban-Shield v2.0 - Smart Rate Limiter for Binance API
Dynamic, context-aware protection that NEVER blocks critical trades

Priority System:
  CRITICAL: SL/TP, trade execution, position closure → Always pass
  NORMAL: Market data, account info → Pass if quota available
  LOW: Scanners, background tasks → Can be delayed/paused

Dynamic Zones:
  GREEN (0-30 req/min): All workers 100% speed
  YELLOW (31-38 req/min): Throttle scanners 50%
  RED (39-40 req/min): Pause non-critical, protect trades only
"""
import time
import asyncio
from typing import Optional, Literal
from collections import deque
from dataclasses import dataclass
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

# Priority levels
Priority = Literal["CRITICAL", "NORMAL", "LOW"]

# Zone thresholds
GREEN_ZONE = 30  # req/min
YELLOW_ZONE = 38  # req/min
RED_ZONE = 40     # req/min

@dataclass
class APICall:
    """Single API call record"""
    timestamp: float
    priority: Priority
    endpoint: str
    worker: str

class BanShield:
    """
    Smart Rate Limiter with 3-tier priority system
    
    Features:
    - Token bucket algorithm with priority lanes
    - Real-time zone detection (Green/Yellow/Red)
    - Context-aware throttling (position-aware)
    - Auto-recovery when load drops
    - Zero impact on critical trades
    """
    
    def __init__(
        self,
        max_requests_per_min: int = 40,
        green_zone: int = 30,
        yellow_zone: int = 38,
        red_zone: int = 40
    ):
        self.max_rpm = max_requests_per_min
        self.green_zone = green_zone
        self.yellow_zone = yellow_zone
        self.red_zone = red_zone
        
        # Token bucket
        self.tokens = float(max_requests_per_min)
        self.max_tokens = float(max_requests_per_min)
        self.refill_rate = max_requests_per_min / 60.0  # tokens per second
        self.last_refill = time.time()
        
        # Call tracking (last 60 seconds)
        self.call_history: deque[APICall] = deque(maxlen=1000)
        
        # Priority queues
        self.critical_queue: asyncio.Queue = asyncio.Queue()
        self.normal_queue: asyncio.Queue = asyncio.Queue()
        self.low_queue: asyncio.Queue = asyncio.Queue()
        
        # State
        self.current_zone: Literal["GREEN", "YELLOW", "RED"] = "GREEN"
        self.paused_workers: set[str] = set()
        
        # Context
        self.open_positions_count = 0
        
        logger.info(
            f"🛡️ BanShield initialized: {max_requests_per_min} req/min "
            f"(Green<{green_zone}, Yellow<{yellow_zone}, Red<{red_zone})"
        )
    
    def _refill_tokens(self):
        """Refill token bucket based on elapsed time"""
        now = time.time()
        elapsed = now - self.last_refill
        
        # Add tokens based on time passed
        new_tokens = elapsed * self.refill_rate
        self.tokens = min(self.max_tokens, self.tokens + new_tokens)
        self.last_refill = now
    
    def _get_current_rpm(self) -> float:
        """Calculate current requests per minute"""
        now = time.time()
        cutoff = now - 60.0  # Last 60 seconds
        
        # Remove old calls
        while self.call_history and self.call_history[0].timestamp < cutoff:
            self.call_history.popleft()
        
        return len(self.call_history)
    
    def _update_zone(self):
        """Update current zone based on request rate"""
        rpm = self._get_current_rpm()
        
        old_zone = self.current_zone
        
        if rpm >= self.red_zone:
            self.current_zone = "RED"
        elif rpm >= self.yellow_zone:
            self.current_zone = "YELLOW"
        else:
            self.current_zone = "GREEN"
        
        # Log zone changes
        if old_zone != self.current_zone:
            logger.warning(
                f"🚦 Zone changed: {old_zone} → {self.current_zone} "
                f"(RPM: {rpm:.1f}/{self.max_rpm})"
            )
    
    def set_position_context(self, open_positions: int):
        """Update context with current open positions"""
        self.open_positions_count = open_positions
    
    async def acquire(
        self,
        priority: Priority = "NORMAL",
        endpoint: str = "unknown",
        worker: str = "unknown"
    ) -> bool:
        """
        Request permission to make API call
        
        Args:
            priority: CRITICAL (always pass), NORMAL (quota), LOW (can wait)
            endpoint: Binance endpoint name
            worker: Worker name making request
            
        Returns:
            True if allowed, False if should skip (LOW priority in RED zone)
        """
        self._refill_tokens()
        self._update_zone()
        
        # CRITICAL: Always pass (SL/TP, trades, position protection)
        if priority == "CRITICAL":
            if self.tokens >= 1:
                self.tokens -= 1
            else:
                # Emergency: allow critical even without tokens
                logger.warning(
                    f"⚠️ CRITICAL call allowed without tokens: {endpoint} "
                    f"({worker})"
                )
            
            self._record_call(priority, endpoint, worker)
            return True
        
        # Context-aware priority boost
        # If we have open positions, boost NORMAL calls (position monitoring)
        effective_priority = priority
        if priority == "NORMAL" and self.open_positions_count > 0:
            effective_priority = "CRITICAL"
            logger.debug(
                f"📈 Priority boost: {priority} → CRITICAL "
                f"(open_positions={self.open_positions_count})"
            )
        
        # RED ZONE: Only CRITICAL passes
        if self.current_zone == "RED":
            if effective_priority == "CRITICAL":
                if self.tokens >= 1:
                    self.tokens -= 1
                else:
                    logger.warning(f"⚠️ Token deficit in RED zone: {endpoint}")
                
                self._record_call(priority, endpoint, worker)
                return True
            else:
                # Block LOW/NORMAL in RED zone
                logger.warning(
                    f"🚫 Blocked {priority} call in RED zone: {endpoint} "
                    f"(worker={worker}, RPM={self._get_current_rpm():.1f})"
                )
                return False
        
        # YELLOW ZONE: Throttle LOW priority
        if self.current_zone == "YELLOW" and priority == "LOW":
            # 50% chance to pass (throttle scanners)
            import random
            if random.random() > 0.5:
                logger.debug(
                    f"⏸️ Throttled LOW call in YELLOW: {endpoint} ({worker})"
                )
                await asyncio.sleep(2)  # Add delay
        
        # GREEN/YELLOW: Check tokens
        if self.tokens >= 1:
            self.tokens -= 1
            self._record_call(priority, endpoint, worker)
            return True
        else:
            # No tokens: wait for refill
            wait_time = 1.0 / self.refill_rate
            logger.debug(
                f"⏳ Waiting {wait_time:.1f}s for token: {endpoint} ({worker})"
            )
            await asyncio.sleep(wait_time)
            
            # Retry after wait
            self._refill_tokens()
            if self.tokens >= 1:
                self.tokens -= 1
                self._record_call(priority, endpoint, worker)
                return True
            else:
                logger.error(f"❌ Still no tokens after wait: {endpoint}")
                return False
    
    def _record_call(self, priority: Priority, endpoint: str, worker: str):
        """Record API call for tracking"""
        call = APICall(
            timestamp=time.time(),
            priority=priority,
            endpoint=endpoint,
            worker=worker
        )
        self.call_history.append(call)
    
    def get_stats(self) -> dict:
        """Get current shield statistics"""
        rpm = self._get_current_rpm()
        
        # Count by priority
        critical_calls = sum(1 for c in self.call_history if c.priority == "CRITICAL")
        normal_calls = sum(1 for c in self.call_history if c.priority == "NORMAL")
        low_calls = sum(1 for c in self.call_history if c.priority == "LOW")
        
        return {
            "current_rpm": rpm,
            "max_rpm": self.max_rpm,
            "zone": self.current_zone,
            "tokens_available": self.tokens,
            "critical_calls_1m": critical_calls,
            "normal_calls_1m": normal_calls,
            "low_calls_1m": low_calls,
            "open_positions": self.open_positions_count,
            "utilization_pct": (rpm / self.max_rpm) * 100
        }
    
    def should_auto_recover(self) -> bool:
        """Check if we should resume paused workers"""
        rpm = self._get_current_rpm()
        return rpm < 25 and self.current_zone == "GREEN"


# Global shield instance
_shield: Optional[BanShield] = None

def init_shield(max_rpm: int = 40) -> BanShield:
    """Initialize global shield instance"""
    global _shield
    _shield = BanShield(max_requests_per_min=max_rpm)
    return _shield

def get_shield() -> BanShield:
    """Get global shield instance"""
    global _shield
    if _shield is None:
        _shield = init_shield()
    return _shield


# Decorator for wrapping Binance API calls
def shield_api_call(
    priority: Priority = "NORMAL",
    endpoint: str = "unknown"
):
    """
    Decorator to protect Binance API calls with rate limiting
    
    Usage:
        @shield_api_call(priority="CRITICAL", endpoint="new_order")
        async def place_order(...):
            ...
    """
    def decorator(func):
        async def wrapper(*args, **kwargs):
            shield = get_shield()
            
            # Get worker name from context
            import inspect
            frame = inspect.currentframe()
            worker = "unknown"
            if frame and frame.f_back:
                worker = frame.f_back.f_globals.get('__name__', 'unknown')
            
            # Acquire permission
            allowed = await shield.acquire(
                priority=priority,
                endpoint=endpoint,
                worker=worker
            )
            
            if not allowed:
                logger.warning(
                    f"🚫 API call blocked by shield: {endpoint} "
                    f"(priority={priority}, worker={worker})"
                )
                return None
            
            # Execute API call
            return await func(*args, **kwargs)
        
        return wrapper
    return decorator


# Auto-classify priority based on endpoint
def auto_classify_priority(endpoint: str) -> Priority:
    """
    Automatically classify API call priority based on endpoint
    
    CRITICAL: Trade execution, SL/TP, position closure
    NORMAL: Market data, account info, position monitoring
    LOW: Scanners, background tasks
    """
    endpoint_lower = endpoint.lower()
    
    # CRITICAL endpoints
    critical_keywords = [
        'order', 'trade', 'position', 'close', 'cancel',
        'stoploss', 'takeprofit', 'liquidation'
    ]
    if any(kw in endpoint_lower for kw in critical_keywords):
        return "CRITICAL"
    
    # LOW endpoints
    low_keywords = [
        'klines', 'ticker', 'depth', 'aggTrades', 'scan'
    ]
    if any(kw in endpoint_lower for kw in low_keywords):
        return "LOW"
    
    # Default: NORMAL
    return "NORMAL"
