"""
Multi-Exchange Balancer - Automatic failover and order routing
Supports Binance and Bybit with automatic failover
"""

import asyncio
from datetime import datetime, timedelta
from typing import Dict, Optional, List
from enum import Enum
import redis.asyncio as redis

class ExchangeStatus(Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    DOWN = "down"
    FROZEN = "frozen"

class ExchangeBalancer:
    """
    Multi-exchange balancer with automatic failover
    
    Supported exchanges: Binance, Bybit
    
    Logic:
    - If exchange A fails → route to B
    - If price spread > X → balance orders
    - Auto-freeze unsafe exchange
    - Auto-resume when stable
    """
    
    def __init__(self, redis_client: Optional[redis.Redis] = None):
        self.redis = redis_client
        self.state_key = "exchange_state"
        
        # Exchange configs
        self.exchanges = {
            'binance': {
                'status': ExchangeStatus.HEALTHY,
                'health_score': 100,
                'last_failure': None,
                'failure_count': 0
            },
            'bybit': {
                'status': ExchangeStatus.HEALTHY,
                'health_score': 100,
                'last_failure': None,
                'failure_count': 0
            }
        }
        
        self.primary = 'binance'
        self.secondary = 'bybit'
        self.price_spread_threshold = 0.005  # 0.5% spread
        self.health_check_interval = 60  # seconds
        self.freeze_threshold = 3  # failures to freeze
        
    async def init(self):
        """Initialize from Redis"""
        if self.redis:
            await self.load_state()
    
    async def load_state(self):
        """Load exchange states from Redis"""
        if not self.redis:
            return
        
        for exchange in self.exchanges.keys():
            state_data = await self.redis.hgetall(f"exchange:{exchange}")
            if state_data:
                self.exchanges[exchange]['status'] = ExchangeStatus(
                    state_data.get(b'status', b'healthy').decode()
                )
                self.exchanges[exchange]['health_score'] = int(
                    state_data.get(b'health_score', 100)
                )
    
    async def save_state(self):
        """Save exchange states to Redis"""
        if not self.redis:
            return
        
        for exchange, data in self.exchanges.items():
            await self.redis.hset(f"exchange:{exchange}", mapping={
                'status': data['status'].value,
                'health_score': str(data['health_score']),
                'failure_count': str(data['failure_count']),
                'last_check': datetime.utcnow().isoformat()
            })
    
    async def check_health(self, exchange: str) -> bool:
        """
        Check health of specific exchange
        Returns: True if healthy, False if down
        """
        
        if exchange not in self.exchanges:
            return False
        
        # In production: actual health check via API
        # For now: simulate via Redis
        if self.redis:
            health_status = await self.redis.get(f"api:health:{exchange}")
            
            if health_status == b'down':
                await self.mark_failure(exchange)
                return False
        
        # If healthy
        await self.mark_healthy(exchange)
        return True
    
    async def mark_failure(self, exchange: str):
        """Mark exchange as failed"""
        
        if exchange not in self.exchanges:
            return
        
        data = self.exchanges[exchange]
        data['failure_count'] += 1
        data['last_failure'] = datetime.utcnow()
        
        if data['failure_count'] >= self.freeze_threshold:
            await self.freeze_exchange(exchange)
        else:
            data['status'] = ExchangeStatus.DEGRADED
            data['health_score'] = max(0, data['health_score'] - 20)
        
        await self.save_state()
    
    async def mark_healthy(self, exchange: str):
        """Mark exchange as healthy"""
        
        if exchange not in self.exchanges:
            return
        
        data = self.exchanges[exchange]
        data['status'] = ExchangeStatus.HEALTHY
        data['health_score'] = min(100, data['health_score'] + 10)
        data['failure_count'] = 0
        
        await self.save_state()
    
    async def freeze_exchange(self, exchange: str):
        """Freeze exchange from trading"""
        
        if exchange not in self.exchanges:
            return
        
        self.exchanges[exchange]['status'] = ExchangeStatus.FROZEN
        self.exchanges[exchange]['health_score'] = 0
        
        if self.redis:
            await self.redis.lpush(
                "exchange:audit",
                f"FROZEN {exchange} at {datetime.utcnow().isoformat()}"
            )
        
        await self.save_state()
    
    async def unfreeze_exchange(self, exchange: str) -> bool:
        """
        Attempt to unfreeze exchange when stable
        Returns: True if unfrozen, False if still unstable
        """
        
        if exchange not in self.exchanges:
            return False
        
        # Test health first
        if not await self.check_health(exchange):
            return False
        
        self.exchanges[exchange]['status'] = ExchangeStatus.HEALTHY
        self.exchanges[exchange]['health_score'] = 100
        self.exchanges[exchange]['failure_count'] = 0
        
        if self.redis:
            await self.redis.lpush(
                "exchange:audit",
                f"UNFROZEN {exchange} at {datetime.utcnow().isoformat()}"
            )
        
        await self.save_state()
        return True
    
    async def get_active_exchange(self) -> str:
        """
        Get primary active exchange for trading
        Automatically failover if primary down
        """
        
        primary_data = self.exchanges[self.primary]
        
        # If primary is healthy, use it
        if primary_data['status'] == ExchangeStatus.HEALTHY:
            return self.primary
        
        # Otherwise try secondary
        secondary_data = self.exchanges[self.secondary]
        if secondary_data['status'] == ExchangeStatus.HEALTHY:
            return self.secondary
        
        # Both degraded - use less-degraded
        if primary_data['health_score'] > secondary_data['health_score']:
            return self.primary
        else:
            return self.secondary
    
    async def check_price_spread(self, symbol: str) -> Dict:
        """
        Check price spread between exchanges
        If spread > threshold → balance orders
        """
        
        if not self.redis:
            return {'spread': 0, 'action': 'none'}
        
        # Get prices from both exchanges
        binance_price = await self.redis.get(f"price:binance:{symbol}")
        bybit_price = await self.redis.get(f"price:bybit:{symbol}")
        
        if not binance_price or not bybit_price:
            return {'spread': 0, 'action': 'none'}
        
        bp = float(binance_price)
        byp = float(bybit_price)
        
        spread = abs(bp - byp) / min(bp, byp)
        
        if spread > self.price_spread_threshold:
            return {
                'spread': spread,
                'action': 'balance_orders',
                'binance_price': bp,
                'bybit_price': byp
            }
        
        return {'spread': spread, 'action': 'none'}
    
    async def get_status(self) -> Dict:
        """Get complete exchange status"""
        
        await self.load_state()
        
        status_dict = {}
        for exchange, data in self.exchanges.items():
            status_dict[exchange] = {
                'status': data['status'].value,
                'health_score': data['health_score'],
                'failure_count': data['failure_count'],
                'last_failure': data['last_failure'].isoformat() if data['last_failure'] else None
            }
        
        return {
            'exchanges': status_dict,
            'active_exchange': await self.get_active_exchange(),
            'timestamp': datetime.utcnow().isoformat()
        }


async def get_exchange_balancer(redis_client: Optional[redis.Redis] = None) -> ExchangeBalancer:
    """Get ExchangeBalancer instance"""
    balancer = ExchangeBalancer(redis_client)
    await balancer.init()
    return balancer
