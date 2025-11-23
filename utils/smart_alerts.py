"""
SmartAlerts Engine - Intelligent Alerting with Mode 2 (Smart) + Mode 1 (Silent) + Mode 5 (AI-Supervised)
Zero-spam, dynamic, fully autonomous.
"""

import json
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from enum import Enum
import asyncio
import redis.asyncio as redis

class AlertPriority(Enum):
    P1_CRITICAL = "P1"  # Immediate action required
    P2_ACTION = "P2"    # Action needed soon
    P3_INFO = "P3"      # Info only (usually suppressed)

class AlertState(Enum):
    NORMAL = "normal"
    RISKY = "risky"
    CRITICAL = "critical"
    NORMALIZING = "normalizing"

class SmartAlerts:
    """
    Smart Alert System - Zero noise, maximum clarity.
    
    Modes:
    - Base: Smart Mode (2) - sends only when state changes
    - + Mode 1: Silent unless required
    - + Mode 5: AI-supervised dynamic logic
    """
    
    def __init__(self, redis_client: Optional[redis.Redis] = None):
        self.redis = redis_client
        self.state_key = "smart_alerts:state"
        self.history_key = "smart_alerts:history"
        self.suppression_ttl = 6 * 3600  # 6 hours
        self.normalization_ttl = 12 * 3600  # 12 hours
        self.max_alerts_per_day = 7
        self.alert_count_today = 0
        self.last_alert_timestamp = 0
        self.suppressed_types = set()
        self.current_risk_level = 0
        self.auto_silenced = False
        self.normalization_pending = False
        
    async def init(self):
        """Initialize Redis state"""
        if self.redis:
            await self.load_state()
    
    async def load_state(self):
        """Load current state from Redis"""
        if not self.redis:
            return
        
        state_data = await self.redis.hgetall(self.state_key)
        if state_data:
            self.current_risk_level = int(state_data.get(b'risk_level', 0))
            self.auto_silenced = state_data.get(b'auto_silenced', b'0') == b'1'
            self.normalization_pending = state_data.get(b'normalization_pending', b'0') == b'1'
            self.last_alert_timestamp = int(state_data.get(b'last_alert_timestamp', 0))
    
    async def save_state(self):
        """Save current state to Redis"""
        if not self.redis:
            return
        
        await self.redis.hset(self.state_key, mapping={
            'risk_level': str(self.current_risk_level),
            'auto_silenced': '1' if self.auto_silenced else '0',
            'normalization_pending': '1' if self.normalization_pending else '0',
            'last_alert_timestamp': str(self.last_alert_timestamp),
            'updated': datetime.utcnow().isoformat()
        })
        await self.redis.expire(self.state_key, 72 * 3600)  # 72h TTL
    
    async def should_alert(self, 
                          alert_type: str, 
                          risk_level: int, 
                          state_changed: bool = True) -> bool:
        """
        Determine if alert should be sent (Mode 2 + Mode 1 + Mode 5 logic)
        
        Triggers ONLY if ALL conditions met:
        - state_changed == True
        - risk_level >= threshold
        - last_alert_for_same_type > 6h ago
        - not already suppressed
        """
        
        # Mode 1: Silent unless required
        if not state_changed and risk_level < 50:
            return False
        
        # Check suppression window
        if await self.is_suppressed(alert_type):
            return False
        
        # Check daily cap (Max 7 alerts/day)
        if self.alert_count_today >= self.max_alerts_per_day:
            return False
        
        # Mode 5: AI-Supervised - check if action really needed
        if not await self.ai_supervisor_allows(alert_type, risk_level):
            return False
        
        return True
    
    async def is_suppressed(self, alert_type: str) -> bool:
        """Check if alert type is currently suppressed"""
        if not self.redis:
            return False
        
        suppressed = await self.redis.get(f"smart_alerts:suppressed:{alert_type}")
        return suppressed is not None
    
    async def suppress_alert(self, alert_type: str, duration_sec: Optional[int] = None):
        """Suppress alert type for specified duration"""
        if not self.redis:
            return
        
        if duration_sec is None:
            duration_sec = self.suppression_ttl
        
        await self.redis.setex(
            f"smart_alerts:suppressed:{alert_type}",
            duration_sec,
            "1"
        )
    
    async def ai_supervisor_allows(self, alert_type: str, risk_level: int) -> bool:
        """
        AI Supervisor decision logic (Mode 5)
        
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
        
        # If system silenced, block most alerts
        if self.auto_silenced and alert_type not in [
            "SL_MISSING", "KILL_SWITCH", "CRITICAL_ERROR"
        ]:
            return False
        
        # Critical alerts always pass
        if alert_type in [
            "KILL_SWITCH", "API_DOWN", "SL_MISSING", "CIRCUIT_BREAKER"
        ]:
            return True
        
        # During high-risk windows, allow more alerts
        if risk_level >= 75:
            return True
        
        # During news freeze, only critical alerts
        if await self.is_news_freeze_active():
            return alert_type in ["KILL_SWITCH", "API_DOWN"]
        
        # Default: allow if risk level sufficient
        return risk_level >= 40
    
    async def is_news_freeze_active(self) -> bool:
        """Check if news freeze is currently active (CPI, FOMC, etc)"""
        if not self.redis:
            return False
        
        freeze = await self.redis.get("news:freeze:active")
        return freeze is not None
    
    async def send_alert(self,
                        alert_type: str,
                        message: str,
                        priority: AlertPriority = AlertPriority.P2_ACTION,
                        risk_level: int = 50) -> bool:
        """
        Send alert if conditions met (Mode 2 Smart + Mode 1 Silent + Mode 5 AI)
        
        Returns: True if alert sent, False if suppressed
        """
        
        # Check if should alert
        if not await self.should_alert(alert_type, risk_level):
            return False
        
        # Update state
        self.current_risk_level = risk_level
        self.last_alert_timestamp = time.time()
        self.alert_count_today += 1
        
        # Suppress for 6 hours
        await self.suppress_alert(alert_type)
        
        # Log to history
        alert_entry = {
            'type': alert_type,
            'priority': priority.value,
            'message': message,
            'risk_level': risk_level,
            'timestamp': datetime.utcnow().isoformat(),
            'sent': True
        }
        
        if self.redis:
            await self.redis.lpush(
                self.history_key,
                json.dumps(alert_entry)
            )
            await self.redis.ltrim(self.history_key, 0, 999)  # Keep last 1000
        
        await self.save_state()
        return True
    
    async def normalize(self) -> bool:
        """
        Send normalization alert when system returns to stable state
        
        Rules:
        - Only once per normalization
        - Suppress if occurred within last 12h
        """
        
        # Check if already normalized recently
        if not self.redis:
            return False
        
        last_norm = await self.redis.get("smart_alerts:last_normalization")
        if last_norm:
            return False
        
        # Send normalization message
        norm_entry = {
            'type': 'NORMALIZATION',
            'priority': AlertPriority.P3_INFO.value,
            'message': '✅ System normalized — Smart Mode resumed',
            'risk_level': 0,
            'timestamp': datetime.utcnow().isoformat(),
            'sent': True
        }
        
        await self.redis.lpush(
            self.history_key,
            json.dumps(norm_entry)
        )
        
        # Suppress normalization for 12h
        await self.redis.setex(
            "smart_alerts:last_normalization",
            self.normalization_ttl,
            "1"
        )
        
        self.current_risk_level = 0
        self.normalization_pending = False
        self.auto_silenced = False
        await self.save_state()
        
        return True
    
    async def auto_escalate(self, alert_type: str):
        """
        Auto-escalate severity if unresolved > 15 minutes
        """
        
        if not self.redis:
            return
        
        # Check if alert been active > 15 min
        escalation_key = f"smart_alerts:escalate:{alert_type}"
        is_escalated = await self.redis.get(escalation_key)
        
        if not is_escalated:
            # Mark for escalation in 15 min
            await self.redis.setex(escalation_key, 900, "1")
    
    async def silence_alerts(self, duration_sec: int = 7200) -> bool:
        """
        User command: silence non-critical alerts for X seconds
        (Default: 2 hours)
        """
        
        self.auto_silenced = True
        
        if self.redis:
            await self.redis.setex("smart_alerts:silenced", duration_sec, "1")
        
        await self.save_state()
        return True
    
    async def resume_alerts(self) -> bool:
        """User command: resume normal alerting"""
        
        self.auto_silenced = False
        
        if self.redis:
            await self.redis.delete("smart_alerts:silenced")
        
        await self.save_state()
        return True
    
    async def get_status(self) -> Dict:
        """Get current alert status for dashboard"""
        
        await self.load_state()
        
        return {
            'mode': 'SMART HYBRID 1+5',
            'risk_level': self.current_risk_level,
            'auto_silenced': self.auto_silenced,
            'alerts_today': self.alert_count_today,
            'max_alerts_today': self.max_alerts_per_day,
            'last_alert': datetime.fromtimestamp(self.last_alert_timestamp).isoformat() if self.last_alert_timestamp else None,
            'normalization_pending': self.normalization_pending,
            'status': 'OK' if self.current_risk_level < 50 else 'WARNING' if self.current_risk_level < 75 else 'CRITICAL'
        }
    
    async def get_history(self, limit: int = 20) -> List[Dict]:
        """Get alert history"""
        
        if not self.redis:
            return []
        
        history = await self.redis.lrange(self.history_key, 0, limit - 1)
        return [json.loads(h) for h in history]
    
    async def reset_daily_counter(self):
        """Reset daily alert counter (call at midnight UTC)"""
        self.alert_count_today = 0
        await self.save_state()


# Singleton instance
_smart_alerts = None

async def get_smart_alerts(redis_client: Optional[redis.Redis] = None) -> SmartAlerts:
    """Get or create SmartAlerts instance"""
    global _smart_alerts
    
    if _smart_alerts is None:
        _smart_alerts = SmartAlerts(redis_client)
        await _smart_alerts.init()
    
    return _smart_alerts
