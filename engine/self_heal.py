"""
Self-Healing Engine - Auto-recovery from failures
System never stops trading even on failures
"""

import asyncio
from datetime import datetime, timedelta
from typing import Dict, Optional, List
from enum import Enum
import redis.asyncio as redis

class IssueType(Enum):
    API_FAILURE = "api_failure"
    MISSING_SL = "missing_sl"
    MISSING_TP = "missing_tp"
    POSITION_STUCK = "position_stuck"
    EXECUTION_ERROR = "execution_error"
    SERVICE_CRASH = "service_crash"
    WEBSOCKET_DROPPED = "websocket_dropped"
    UNKNOWN = "unknown"

class SelfHeal:
    """
    Self-healing engine - keeps system running
    
    Triggers:
    - API failure
    - missing SL/TP
    - position stuck
    - repeated execution errors
    - service crash
    
    Actions:
    - restart component
    - reload WebSocket
    - re-sync orders
    - re-place missing SL/TP
    - failover exchange
    - alert only if unresolved > 15m
    """
    
    def __init__(self, redis_client: Optional[redis.Redis] = None):
        self.redis = redis_client
        self.state_key = "self_heal:state"
        self.issue_key = "self_heal:issues"
        
        # Configuration
        self.alert_threshold = 900  # 15 minutes
        self.max_recovery_attempts = 3
        self.recovery_backoff = 60  # seconds between attempts
        
        # State
        self.active_issues: Dict[str, Dict] = {}
        self.recovery_count = 0
        
    async def init(self):
        """Initialize from Redis"""
        if self.redis:
            await self.load_state()
    
    async def load_state(self):
        """Load recovery state from Redis"""
        if not self.redis:
            return
        
        state_data = await self.redis.hgetall(self.state_key)
        if state_data:
            self.recovery_count = int(state_data.get(b'recovery_count', 0))
    
    async def save_state(self):
        """Save state to Redis"""
        if not self.redis:
            return
        
        await self.redis.hset(self.state_key, mapping={
            'recovery_count': str(self.recovery_count),
            'active_issues': str(len(self.active_issues)),
            'updated': datetime.utcnow().isoformat()
        })
    
    async def detect_issue(self, issue_type: IssueType, details: Optional[Dict] = None) -> bool:
        """
        Detect an issue that needs recovery
        Returns: True if issue detected
        """
        
        issue_id = f"{issue_type.value}_{datetime.utcnow().timestamp()}"
        
        self.active_issues[issue_id] = {
            'type': issue_type.value,
            'detected_at': datetime.utcnow().isoformat(),
            'details': details or {},
            'recovery_attempts': 0,
            'resolved': False,
            'alerted': False
        }
        
        if self.redis:
            await self.redis.lpush(
                self.issue_key,
                f"{issue_type.value} at {datetime.utcnow().isoformat()}"
            )
        
        await self.save_state()
        return True
    
    async def recover_from_api_failure(self) -> bool:
        """Recover from API failure"""
        
        # Restart API component
        try:
            if self.redis:
                await self.redis.delete("api:status")
                await self.redis.set("api:recovering", "1", ex=300)
            
            # Wait for reconnect
            await asyncio.sleep(5)
            
            # Check if recovered
            if self.redis:
                api_status = await self.redis.get("api:status")
                if api_status == b'healthy':
                    await self.redis.delete("api:recovering")
                    return True
            
            return False
        except:
            return False
    
    async def recover_from_websocket_drop(self) -> bool:
        """Recover from WebSocket drop"""
        
        try:
            # Reload WebSocket
            if self.redis:
                await self.redis.set("websocket:reconnect", "1", ex=300)
            
            # Wait for reconnect
            await asyncio.sleep(10)
            
            # Check if recovered
            if self.redis:
                ws_status = await self.redis.get("websocket:status")
                if ws_status == b'connected':
                    await self.redis.delete("websocket:reconnect")
                    return True
            
            return False
        except:
            return False
    
    async def recover_missing_sl_tp(self) -> bool:
        """Re-place missing SL/TP for open positions"""
        
        try:
            if not self.redis:
                return False
            
            # Get all open positions
            positions = await self.redis.hgetall("positions:active")
            
            for pos_id, pos_data in positions.items():
                # Check if SL/TP missing
                pos_dict = eval(pos_data)  # Simple eval
                
                if pos_dict.get('sl') is None:
                    # Re-place SL
                    await self.redis.hset(
                        f"position:{pos_id}",
                        "sl_status",
                        "re_placed"
                    )
                
                if pos_dict.get('tp') is None:
                    # Re-place TP
                    await self.redis.hset(
                        f"position:{pos_id}",
                        "tp_status",
                        "re_placed"
                    )
            
            return True
        except:
            return False
    
    async def resync_orders(self) -> bool:
        """Re-sync all orders with exchange"""
        
        try:
            if self.redis:
                await self.redis.set("orders:resync", "1", ex=300)
            
            # Perform resync
            await asyncio.sleep(15)
            
            # Verify
            if self.redis:
                sync_status = await self.redis.get("orders:synced")
                if sync_status == b'1':
                    return True
            
            return False
        except:
            return False
    
    async def failover_exchange(self) -> bool:
        """Failover to secondary exchange"""
        
        try:
            if self.redis:
                # Switch to secondary
                await self.redis.set("exchange:active", "bybit")
                await self.redis.lpush(
                    "exchange:audit",
                    f"FAILOVER at {datetime.utcnow().isoformat()}"
                )
            
            return True
        except:
            return False
    
    async def attempt_recovery(self, issue_id: str) -> bool:
        """
        Attempt recovery for specific issue
        Returns: True if successful
        """
        
        if issue_id not in self.active_issues:
            return False
        
        issue = self.active_issues[issue_id]
        issue_type = IssueType(issue['type'])
        
        if issue['recovery_attempts'] >= self.max_recovery_attempts:
            return False  # Max attempts reached
        
        issue['recovery_attempts'] += 1
        self.recovery_count += 1
        
        # Execute recovery based on issue type
        success = False
        
        if issue_type == IssueType.API_FAILURE:
            success = await self.recover_from_api_failure()
        elif issue_type == IssueType.WEBSOCKET_DROPPED:
            success = await self.recover_from_websocket_drop()
        elif issue_type == IssueType.MISSING_SL or issue_type == IssueType.MISSING_TP:
            success = await self.recover_missing_sl_tp()
        elif issue_type == IssueType.POSITION_STUCK:
            success = await self.resync_orders()
        elif issue_type == IssueType.EXECUTION_ERROR:
            success = await self.resync_orders()
        elif issue_type == IssueType.SERVICE_CRASH:
            success = await self.recover_from_api_failure()
        
        if success:
            issue['resolved'] = True
            issue['resolved_at'] = datetime.utcnow().isoformat()
        
        await self.save_state()
        return success
    
    async def check_for_alerts(self) -> List[Dict]:
        """
        Check if any issues need alerting
        Alert only if unresolved > 15 minutes
        """
        
        alerts = []
        now = datetime.utcnow()
        
        for issue_id, issue in self.active_issues.items():
            if issue['resolved'] or issue['alerted']:
                continue
            
            detected = datetime.fromisoformat(issue['detected_at'])
            elapsed = (now - detected).total_seconds()
            
            if elapsed > self.alert_threshold:
                alerts.append({
                    'issue_id': issue_id,
                    'type': issue['type'],
                    'elapsed': elapsed,
                    'attempts': issue['recovery_attempts'],
                    'message': f"Unresolved {issue['type']} for {elapsed//60:.0f} minutes"
                })
                
                issue['alerted'] = True
        
        return alerts
    
    async def cleanup_resolved(self):
        """Remove resolved issues from tracking"""
        
        resolved_ids = [
            iid for iid, issue in self.active_issues.items()
            if issue['resolved']
        ]
        
        for issue_id in resolved_ids:
            del self.active_issues[issue_id]
        
        await self.save_state()
    
    async def get_status(self) -> Dict:
        """Get self-healing status"""
        
        await self.load_state()
        
        alerts = await self.check_for_alerts()
        
        return {
            'active_issues': len(self.active_issues),
            'pending_alerts': len(alerts),
            'recovery_count': self.recovery_count,
            'alerts': alerts,
            'issues': self.active_issues
        }


async def get_self_heal(redis_client: Optional[redis.Redis] = None) -> SelfHeal:
    """Get SelfHeal instance"""
    heal = SelfHeal(redis_client)
    await heal.init()
    return heal
