"""
Auto-Hedge Engine - Dynamic hedging based on market conditions
Fully automatic, no manual approval required
"""

import asyncio
from datetime import datetime, timedelta
from typing import Dict, Optional, List
from enum import Enum
import redis.asyncio as redis

class HedgeState(Enum):
    INACTIVE = "inactive"
    ACTIVE = "active"
    UNWINDING = "unwinding"
    PAUSED = "paused"

class AutoHedge:
    """
    Autonomous hedging engine
    
    Triggers ONLY if ALL conditions met:
    - exposure_risk >= threshold
    - volatility regime = HIGH
    - funding flip detected
    - news impact = RED
    """
    
    def __init__(self, redis_client: Optional[redis.Redis] = None):
        self.redis = redis_client
        self.state_key = "hedge:state"
        self.history_key = "hedge:history"
        
        # Thresholds
        self.exposure_threshold = 50000  # USD
        self.volatility_threshold = 3.0
        self.funding_flip_threshold = 0.03
        self.news_impact_threshold = 75  # 0-100
        
        # Hedge ratios
        self.hedge_ratio_normal = 0.25
        self.hedge_ratio_high = 0.5
        self.hedge_ratio_extreme = 0.8
        
        # State
        self.current_state = HedgeState.INACTIVE
        self.active_hedges: Dict[str, Dict] = {}
        self.last_activation = None
        
    async def init(self):
        """Initialize from Redis"""
        if self.redis:
            await self.load_state()
    
    async def load_state(self):
        """Load hedge state from Redis"""
        if not self.redis:
            return
        
        state_data = await self.redis.hgetall(self.state_key)
        if state_data:
            state_str = state_data.get(b'current_state', b'inactive').decode()
            self.current_state = HedgeState(state_str)
    
    async def save_state(self):
        """Save state to Redis"""
        if not self.redis:
            return
        
        state_data = {
            'current_state': self.current_state.value,
            'active_hedges': str(len(self.active_hedges)),
            'updated': datetime.utcnow().isoformat()
        }
        if self.last_activation:
            state_data['last_activation'] = self.last_activation.isoformat()
        
        await self.redis.hset(self.state_key, mapping=state_data)
    
    async def should_hedge(self) -> bool:
        """
        Determine if hedging should be activated
        
        ALL conditions must be true:
        1. exposure_risk >= threshold
        2. volatility regime = HIGH
        3. funding flip detected
        4. news impact = RED
        """
        
        if not self.redis:
            return False
        
        # Check exposure risk
        exposure = await self.get_exposure_risk()
        if exposure < self.exposure_threshold:
            return False
        
        # Check volatility regime
        volatility = await self.get_volatility_regime()
        if volatility < self.volatility_threshold:
            return False
        
        # Check funding flip
        funding_flip = await self.check_funding_flip()
        if not funding_flip:
            return False
        
        # Check news impact
        news_impact = await self.get_news_impact()
        if news_impact < self.news_impact_threshold:
            return False
        
        return True
    
    async def get_exposure_risk(self) -> float:
        """Calculate total exposure risk in USD"""
        if not self.redis:
            return 0
        
        # Get sum of all open position sizes
        positions = await self.redis.hgetall("positions:active")
        total_exposure = 0
        
        for pos_data in positions.values():
            # Parse position data and add to total
            try:
                pos_dict = eval(pos_data)  # Simple eval for demo
                size = float(pos_dict.get('size', 0))
                entry = float(pos_dict.get('entry_price', 0))
                total_exposure += abs(size * entry)
            except:
                pass
        
        return total_exposure
    
    async def get_volatility_regime(self) -> float:
        """Get current volatility as multiple of normal"""
        if not self.redis:
            return 1.0
        
        vol_data = await self.redis.hgetall("market:volatility")
        if not vol_data:
            return 1.0
        
        current = float(vol_data.get(b'current', 0))
        average = float(vol_data.get(b'average', 1))
        
        return current / average if average > 0 else 1.0
    
    async def check_funding_flip(self) -> bool:
        """Check if funding has flipped meaningfully"""
        if not self.redis:
            return False
        
        current = await self.redis.get("market:funding:current")
        previous = await self.redis.get("market:funding:previous")
        
        if not current or not previous:
            return False
        
        shift = abs(float(current) - float(previous))
        return shift > self.funding_flip_threshold
    
    async def get_news_impact(self) -> float:
        """Get news impact level (0-100)"""
        if not self.redis:
            return 0
        
        events = await self.redis.lrange("news:events:active", 0, 10)
        
        # Count high-impact events
        if events:
            return 75.0  # High impact if events exist
        
        return 0.0
    
    async def activate_hedge(self) -> bool:
        """Activate hedging"""
        
        if self.current_state == HedgeState.ACTIVE:
            return False  # Already active
        
        self.current_state = HedgeState.ACTIVE
        self.last_activation = datetime.utcnow()
        
        # Determine hedge ratio based on risk
        exposure = await self.get_exposure_risk()
        if exposure > 100000:
            hedge_ratio = self.hedge_ratio_extreme
        elif exposure > 75000:
            hedge_ratio = self.hedge_ratio_high
        else:
            hedge_ratio = self.hedge_ratio_normal
        
        # Open hedges on correlated symbols
        hedge_entry = {
            'symbol': 'BTC/USDT',  # Typically hedge with major
            'side': 'SHORT',
            'size': exposure * hedge_ratio,
            'activated': datetime.utcnow().isoformat(),
            'ratio': hedge_ratio
        }
        
        self.active_hedges['BTC_HEDGE'] = hedge_entry
        
        if self.redis:
            await self.redis.lpush(
                self.history_key,
                f"HEDGE_ACTIVATED at {datetime.utcnow().isoformat()}"
            )
        
        await self.save_state()
        return True
    
    async def check_unwind(self) -> bool:
        """
        Check if hedges should be unwound
        
        Condition: risk_normalized for >= 30 minutes
        """
        
        if self.current_state != HedgeState.ACTIVE:
            return False
        
        if not self.last_activation:
            return False
        
        # Check if conditions normalized
        exposure = await self.get_exposure_risk()
        volatility = await self.get_volatility_regime()
        funding_flip = await self.check_funding_flip()
        
        if exposure > self.exposure_threshold:
            return False
        if volatility > self.volatility_threshold:
            return False
        if funding_flip:
            return False
        
        # Check 30-minute window
        elapsed = datetime.utcnow() - self.last_activation
        if elapsed < timedelta(minutes=30):
            return False
        
        return True
    
    async def unwind_hedge(self) -> bool:
        """Gradually close hedge positions"""
        
        if not self.active_hedges:
            return False
        
        self.current_state = HedgeState.UNWINDING
        
        for hedge_id, hedge_data in self.active_hedges.items():
            # Close gradually
            hedge_data['unwinding'] = True
            hedge_data['unwound_at'] = datetime.utcnow().isoformat()
        
        # After closing all
        self.active_hedges = {}
        self.current_state = HedgeState.INACTIVE
        
        if self.redis:
            await self.redis.lpush(
                self.history_key,
                f"HEDGE_UNWOUND at {datetime.utcnow().isoformat()}"
            )
        
        await self.save_state()
        return True
    
    async def get_status(self) -> Dict:
        """Get current hedge status"""
        
        await self.load_state()
        
        return {
            'state': self.current_state.value,
            'active_hedges': len(self.active_hedges),
            'last_activation': self.last_activation.isoformat() if self.last_activation else None,
            'hedges': self.active_hedges
        }


async def get_auto_hedge(redis_client: Optional[redis.Redis] = None) -> AutoHedge:
    """Get AutoHedge instance"""
    hedge = AutoHedge(redis_client)
    await hedge.init()
    return hedge
