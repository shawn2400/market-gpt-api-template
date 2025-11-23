"""
Auto-Scaler - PnL-Adaptive position sizing
Automatically scales based on 48-hour performance
"""

from datetime import datetime, timedelta
from typing import Dict, Optional
from enum import Enum
import redis.asyncio as redis

class ScalingMode(Enum):
    NORMAL = "normal"
    BOOST = "boost"  # Growing profits
    PROTECT = "protect"  # Losses
    FROZEN = "frozen"  # Emergency freeze

class AutoScaler:
    """
    PnL-Adaptive auto-scaling
    
    Logic:
    if last_48h_pnl > +X%:
        increase size by +10–20%
    
    if last_48h_pnl < –X%:
        reduce size by –30–50%
        switch to protection mode
    
    Hard limits:
    - Never exceed max risk per trade
    - Never scale twice in < 24h
    - Admin override always respected
    """
    
    def __init__(self, redis_client: Optional[redis.Redis] = None):
        self.redis = redis_client
        self.state_key = "scaler:state"
        
        # Thresholds
        self.profit_threshold = 5.0  # 5% profit to boost
        self.loss_threshold = -3.0   # -3% loss to protect
        
        # Scaling factors
        self.boost_factor = 1.15  # +15% on wins
        self.protect_factor = 0.5  # -50% on losses
        self.max_boost_factor = 1.5  # Never boost more than 50%
        
        # Constraints
        self.min_scale_interval = 86400  # 24 hours minimum
        self.max_size_per_trade = 10000  # USD
        self.max_portfolio_risk = 0.02  # 2% max risk
        
        # State
        self.current_mode = ScalingMode.NORMAL
        self.current_size_multiplier = 1.0
        self.last_scale_time = None
        
    async def init(self):
        """Initialize from Redis"""
        if self.redis:
            await self.load_state()
    
    async def load_state(self):
        """Load scaler state from Redis"""
        if not self.redis:
            return
        
        state_data = await self.redis.hgetall(self.state_key)
        if state_data:
            mode_str = state_data.get(b'mode', b'normal').decode()
            self.current_mode = ScalingMode(mode_str)
            self.current_size_multiplier = float(
                state_data.get(b'size_multiplier', 1.0)
            )
    
    async def save_state(self):
        """Save scaler state to Redis"""
        if not self.redis:
            return
        
        state_data = {
            'mode': self.current_mode.value,
            'size_multiplier': str(self.current_size_multiplier),
            'updated': datetime.utcnow().isoformat()
        }
        if self.last_scale_time:
            state_data['last_scale'] = self.last_scale_time.isoformat()
        
        await self.redis.hset(self.state_key, mapping=state_data)
    
    async def get_48h_pnl(self) -> float:
        """
        Get 48-hour PnL percentage
        Returns: percentage change (-100 to +100)
        """
        
        if not self.redis:
            return 0.0
        
        pnl_data = await self.redis.hgetall("pnl:48h")
        if not pnl_data:
            return 0.0
        
        pnl_pct = float(pnl_data.get(b'pct_change', 0))
        return pnl_pct
    
    async def should_scale(self) -> tuple[bool, str]:
        """
        Determine if scaling should occur
        Returns: (should_scale, reason)
        """
        
        # Check minimum interval
        if self.last_scale_time:
            elapsed = datetime.utcnow() - self.last_scale_time
            if elapsed < timedelta(seconds=self.min_scale_interval):
                return False, "Min scale interval not met"
        
        # Check if in frozen mode
        if self.current_mode == ScalingMode.FROZEN:
            return False, "Frozen by admin"
        
        pnl = await self.get_48h_pnl()
        
        if pnl > self.profit_threshold:
            return True, f"Profit threshold met: {pnl:.1f}%"
        
        if pnl < self.loss_threshold:
            return True, f"Loss threshold met: {pnl:.1f}%"
        
        return False, f"Within range: {pnl:.1f}%"
    
    async def boost_scale(self, current_base_size: float) -> float:
        """
        Increase position size on profit
        
        Formula: current_size * boost_factor (capped at max_boost_factor)
        """
        
        pnl = await self.get_48h_pnl()
        
        # Calculate how much to boost
        if pnl > self.profit_threshold:
            boost_level = min(1 + (pnl / 100) * 0.2, self.max_boost_factor)
            new_multiplier = self.current_size_multiplier * boost_level
        else:
            new_multiplier = self.current_size_multiplier
        
        # Check hard limit
        new_size = current_base_size * new_multiplier
        if new_size > self.max_size_per_trade:
            new_multiplier = self.max_size_per_trade / current_base_size
        
        self.current_size_multiplier = new_multiplier
        self.current_mode = ScalingMode.BOOST
        self.last_scale_time = datetime.utcnow()
        
        await self.save_state()
        
        return current_base_size * new_multiplier
    
    async def protect_scale(self, current_base_size: float) -> float:
        """
        Reduce position size on loss
        Switch to protection mode
        
        Formula: current_size * protect_factor
        """
        
        # Reduce aggressively on losses
        new_multiplier = self.current_size_multiplier * self.protect_factor
        new_size = current_base_size * new_multiplier
        
        self.current_size_multiplier = new_multiplier
        self.current_mode = ScalingMode.PROTECT
        self.last_scale_time = datetime.utcnow()
        
        if self.redis:
            await self.redis.lpush(
                "scaler:audit",
                f"PROTECT MODE at {datetime.utcnow().isoformat()}"
            )
        
        await self.save_state()
        
        return new_size
    
    async def get_next_size(self, base_size: float) -> float:
        """
        Get next position size (multiplier applied)
        """
        
        should_scale, reason = await self.should_scale()
        
        if not should_scale:
            return base_size * self.current_size_multiplier
        
        pnl = await self.get_48h_pnl()
        
        if pnl > self.profit_threshold:
            return await self.boost_scale(base_size)
        else:
            return await self.protect_scale(base_size)
    
    async def freeze(self):
        """Admin command: freeze scaling"""
        self.current_mode = ScalingMode.FROZEN
        await self.save_state()
    
    async def unfreeze(self):
        """Admin command: unfreeze scaling"""
        self.current_mode = ScalingMode.NORMAL
        await self.save_state()
    
    async def reset_to_normal(self):
        """Admin command: reset to normal mode"""
        self.current_mode = ScalingMode.NORMAL
        self.current_size_multiplier = 1.0
        self.last_scale_time = None
        await self.save_state()
    
    async def get_status(self) -> Dict:
        """Get scaler status"""
        
        await self.load_state()
        
        pnl = await self.get_48h_pnl()
        should_scale, reason = await self.should_scale()
        
        return {
            'mode': self.current_mode.value,
            'size_multiplier': self.current_size_multiplier,
            'pnl_48h': pnl,
            'should_scale': should_scale,
            'reason': reason,
            'last_scale': self.last_scale_time.isoformat() if self.last_scale_time else None
        }


async def get_auto_scaler(redis_client: Optional[redis.Redis] = None) -> AutoScaler:
    """Get AutoScaler instance"""
    scaler = AutoScaler(redis_client)
    await scaler.init()
    return scaler
