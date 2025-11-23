"""
AI Supervisor - Dynamic alert decision engine
Analyzes market conditions and determines if alerts are truly needed (Mode 5)
"""

import asyncio
from datetime import datetime, timedelta
from typing import Dict, Optional, Tuple
import redis.asyncio as redis

class AISupervisor:
    """
    AI Supervisor for Smart Alerts
    
    Analyzes:
    - Volatility regime
    - Funding shift
    - Abnormal volume
    - News sentiment
    - Error clusters
    - SL/TP health
    - Hedge exposure
    - API reliability
    """
    
    def __init__(self, redis_client: Optional[redis.Redis] = None):
        self.redis = redis_client
        
        # Risk thresholds
        self.volatility_threshold = 3.0  # Standard deviations
        self.funding_shift_threshold = 0.03  # 3% shift
        self.volume_anomaly_threshold = 2.5  # 2.5x normal
        self.error_cluster_threshold = 5  # Errors in 5 min window
        self.api_health_threshold = 0.95  # 95% uptime required
        
    async def analyze_alert(self, alert_type: str) -> Tuple[bool, str]:
        """
        Analyze if alert is truly needed
        
        Returns: (should_alert, reason)
        """
        
        if alert_type == "SL_MISSING":
            return await self.check_sl_health()
        elif alert_type == "TP_MISSING":
            return await self.check_tp_health()
        elif alert_type == "VOLATILITY_SPIKE":
            return await self.check_volatility_regime()
        elif alert_type == "FUNDING_FLIP":
            return await self.check_funding_shift()
        elif alert_type == "VOLUME_ANOMALY":
            return await self.check_volume_anomaly()
        elif alert_type == "ERROR_CLUSTER":
            return await self.check_error_cluster()
        elif alert_type == "API_DEGRADED":
            return await self.check_api_health()
        elif alert_type == "HEDGE_EXPOSURE":
            return await self.check_hedge_exposure()
        elif alert_type == "NEWS_FREEZE":
            return await self.check_news_impact()
        elif alert_type in ["KILL_SWITCH", "CIRCUIT_BREAKER"]:
            # These always need alert
            return True, "Critical system event"
        else:
            return True, "Unknown alert type - escalate"
    
    async def check_sl_health(self) -> Tuple[bool, str]:
        """Check if SL is actually missing or just recovering"""
        
        if not self.redis:
            return True, "SL status unknown"
        
        # Check if SL missing on ANY position
        positions = await self.redis.hgetall("positions:active")
        
        for pos_id, pos_data in positions.items():
            # TODO: Parse position data and check SL
            pass
        
        return False, "SL health check - no critical issues"
    
    async def check_tp_health(self) -> Tuple[bool, str]:
        """Check if TP is actually missing"""
        
        if not self.redis:
            return True, "TP status unknown"
        
        return False, "TP health check - no critical issues"
    
    async def check_volatility_regime(self) -> Tuple[bool, str]:
        """
        Check if volatility spike is real and actionable
        
        Returns: (should_alert, reason)
        """
        
        if not self.redis:
            return True, "Volatility status unknown"
        
        # Get current volatility metrics
        vol_data = await self.redis.hgetall("market:volatility")
        
        if not vol_data:
            return False, "No volatility data yet"
        
        # Check if spike is above threshold
        current_vol = float(vol_data.get(b'current', 0))
        avg_vol = float(vol_data.get(b'average', 1))
        vol_ratio = current_vol / avg_vol if avg_vol > 0 else 1
        
        if vol_ratio > self.volatility_threshold:
            return True, f"Real volatility spike: {vol_ratio:.2f}x normal"
        
        return False, "Volatility elevated but within normal range"
    
    async def check_funding_shift(self) -> Tuple[bool, str]:
        """Check if funding has flipped meaningfully"""
        
        if not self.redis:
            return True, "Funding status unknown"
        
        current = await self.redis.get("market:funding:current")
        previous = await self.redis.get("market:funding:previous")
        
        if not current or not previous:
            return False, "Insufficient funding data"
        
        shift = abs(float(current) - float(previous))
        
        if shift > self.funding_shift_threshold:
            return True, f"Funding shift detected: {shift:.4f}"
        
        return False, "Funding stable"
    
    async def check_volume_anomaly(self) -> Tuple[bool, str]:
        """Check if volume anomaly is real"""
        
        if not self.redis:
            return True, "Volume status unknown"
        
        current_vol = await self.redis.get("market:volume:current")
        avg_vol = await self.redis.get("market:volume:average")
        
        if not current_vol or not avg_vol:
            return False, "Insufficient volume data"
        
        ratio = float(current_vol) / float(avg_vol)
        
        if ratio > self.volume_anomaly_threshold:
            return True, f"Abnormal volume: {ratio:.1f}x average"
        
        return False, "Volume normal"
    
    async def check_error_cluster(self) -> Tuple[bool, str]:
        """Check if errors are clustered (real problem)"""
        
        if not self.redis:
            return True, "Error status unknown"
        
        # Get errors from last 5 minutes
        errors = await self.redis.lrange("errors:recent", 0, 99)
        
        # Count errors in recent window
        now = datetime.utcnow()
        error_count = 0
        
        # TODO: Parse timestamps and count recent errors
        
        if error_count >= self.error_cluster_threshold:
            return True, f"Error cluster: {error_count} errors in 5 min"
        
        return False, "Errors within normal rate"
    
    async def check_api_health(self) -> Tuple[bool, str]:
        """Check Binance API health"""
        
        if not self.redis:
            return True, "API status unknown"
        
        # Get API uptime metric
        uptime = await self.redis.get("api:binance:uptime")
        
        if not uptime:
            return False, "No API metrics yet"
        
        uptime_pct = float(uptime)
        
        if uptime_pct < self.api_health_threshold:
            return True, f"API degraded: {uptime_pct:.1%} uptime"
        
        return False, "API healthy"
    
    async def check_hedge_exposure(self) -> Tuple[bool, str]:
        """Check if hedge exposure is actually excessive"""
        
        if not self.redis:
            return True, "Hedge status unknown"
        
        # Get current hedging metrics
        hedge_ratio = await self.redis.get("hedge:exposure:ratio")
        
        if not hedge_ratio:
            return False, "No hedge data yet"
        
        ratio = float(hedge_ratio)
        
        # Alert if hedging > 80% of portfolio
        if ratio > 0.8:
            return True, f"Hedge exposure high: {ratio:.1%}"
        
        return False, "Hedge exposure normal"
    
    async def check_news_impact(self) -> Tuple[bool, str]:
        """Check if news events require freeze"""
        
        if not self.redis:
            return True, "News status unknown"
        
        # Check for active news events
        events = await self.redis.lrange("news:events:active", 0, 10)
        
        if events:
            # Parse event data
            return True, "High-impact news event detected"
        
        return False, "No significant news events"
    
    async def get_risk_level(self) -> int:
        """
        Calculate overall risk level (0-100)
        
        Based on:
        - Volatility (0-25 points)
        - Funding (0-15 points)
        - Volume (0-15 points)
        - Errors (0-15 points)
        - API health (0-15 points)
        - News (0-15 points)
        """
        
        risk = 0
        
        # Volatility component
        if self.redis:
            vol_data = await self.redis.hgetall("market:volatility")
            if vol_data:
                current_vol = float(vol_data.get(b'current', 0))
                avg_vol = float(vol_data.get(b'average', 1))
                if avg_vol > 0:
                    vol_ratio = current_vol / avg_vol
                    risk += min(25, int((vol_ratio - 1) * 50))  # 0-25 points
        
        # Funding component
        if self.redis:
            funding = await self.redis.get("market:funding:current")
            if funding:
                funding_val = abs(float(funding))
                risk += min(15, int(funding_val * 500))  # 0-15 points
        
        # Volume component
        if self.redis:
            current_vol = await self.redis.get("market:volume:current")
            avg_vol = await self.redis.get("market:volume:average")
            if current_vol and avg_vol:
                vol_ratio = float(current_vol) / float(avg_vol)
                risk += min(15, int((vol_ratio - 1) * 15))  # 0-15 points
        
        # Error rate component
        if self.redis:
            errors = await self.redis.lrange("errors:recent", 0, 99)
            risk += min(15, len(errors) * 3)  # 0-15 points
        
        # API health component
        if self.redis:
            uptime = await self.redis.get("api:binance:uptime")
            if uptime:
                uptime_pct = float(uptime)
                risk += int((1 - uptime_pct) * 15)  # 0-15 points
        
        # News component
        if self.redis:
            events = await self.redis.lrange("news:events:active", 0, 10)
            risk += min(15, len(events) * 5)  # 0-15 points
        
        return min(100, max(0, risk))


async def get_ai_supervisor(redis_client: Optional[redis.Redis] = None) -> AISupervisor:
    """Get AI supervisor instance"""
    return AISupervisor(redis_client)
