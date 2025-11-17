"""
📊 API Call Tracker - Real-time monitoring of Binance API usage

Tracks all API calls across workers with:
- Per-worker breakdown
- Rolling averages (1min, 5min, 15min)
- Priority distribution
- Zone history
- Auto-alerts on threshold violations
"""
import time
from typing import Dict, List, Optional
from collections import deque, defaultdict
from dataclasses import dataclass, asdict
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

@dataclass
class CallRecord:
    """Single API call record"""
    timestamp: float
    worker: str
    endpoint: str
    priority: str
    zone: str
    
class APICallTracker:
    """
    Real-time API call tracking and analytics
    
    Features:
    - Tracks all calls with full context
    - Calculates rolling averages
    - Per-worker statistics
    - Priority distribution
    - Zone transition history
    """
    
    def __init__(self, history_minutes: int = 15):
        self.history_minutes = history_minutes
        self.history_seconds = history_minutes * 60
        
        # Call history (last 15 minutes)
        self.calls: deque[CallRecord] = deque(maxlen=10000)
        
        # Zone transitions
        self.zone_history: List[Dict] = []
        
        # Current zone
        self.current_zone = "GREEN"
        
        logger.info(f"📊 APICallTracker initialized ({history_minutes}min history)")
    
    def record_call(
        self,
        worker: str,
        endpoint: str,
        priority: str,
        zone: str
    ):
        """Record a new API call"""
        record = CallRecord(
            timestamp=time.time(),
            worker=worker,
            endpoint=endpoint,
            priority=priority,
            zone=zone
        )
        self.calls.append(record)
        
        # Track zone transitions
        if zone != self.current_zone:
            self.zone_history.append({
                "timestamp": datetime.now().isoformat(),
                "from_zone": self.current_zone,
                "to_zone": zone,
                "rpm_at_transition": self.get_rpm(60)
            })
            self.current_zone = zone
            
            # Keep only last 100 transitions
            if len(self.zone_history) > 100:
                self.zone_history = self.zone_history[-100:]
    
    def _cleanup_old_calls(self, max_age_seconds: float):
        """Remove calls older than max_age_seconds"""
        cutoff = time.time() - max_age_seconds
        while self.calls and self.calls[0].timestamp < cutoff:
            self.calls.popleft()
    
    def get_rpm(self, window_seconds: int = 60) -> float:
        """Get requests per minute for given time window"""
        self._cleanup_old_calls(window_seconds)
        cutoff = time.time() - window_seconds
        
        count = sum(1 for c in self.calls if c.timestamp >= cutoff)
        
        # Normalize to RPM
        minutes = window_seconds / 60.0
        return count / minutes if minutes > 0 else 0
    
    def get_rolling_averages(self) -> Dict[str, float]:
        """Get 1min, 5min, 15min rolling averages"""
        return {
            "rpm_1min": self.get_rpm(60),
            "rpm_5min": self.get_rpm(300),
            "rpm_15min": self.get_rpm(900)
        }
    
    def get_worker_breakdown(self, window_seconds: int = 60) -> Dict[str, int]:
        """Get call count per worker"""
        cutoff = time.time() - window_seconds
        
        worker_counts: Dict[str, int] = defaultdict(int)
        for call in self.calls:
            if call.timestamp >= cutoff:
                worker_counts[call.worker] += 1
        
        return dict(worker_counts)
    
    def get_priority_distribution(self, window_seconds: int = 60) -> Dict[str, int]:
        """Get call count per priority level"""
        cutoff = time.time() - window_seconds
        
        priority_counts: Dict[str, int] = defaultdict(int)
        for call in self.calls:
            if call.timestamp >= cutoff:
                priority_counts[call.priority] += 1
        
        return dict(priority_counts)
    
    def get_endpoint_breakdown(self, window_seconds: int = 60, top_n: int = 10) -> Dict[str, int]:
        """Get top N endpoints by call count"""
        cutoff = time.time() - window_seconds
        
        endpoint_counts: Dict[str, int] = defaultdict(int)
        for call in self.calls:
            if call.timestamp >= cutoff:
                endpoint_counts[call.endpoint] += 1
        
        # Sort and get top N
        sorted_endpoints = sorted(
            endpoint_counts.items(),
            key=lambda x: x[1],
            reverse=True
        )
        return dict(sorted_endpoints[:top_n])
    
    def get_full_stats(self, window_seconds: int = 60) -> Dict:
        """Get comprehensive statistics"""
        rpm = self.get_rpm(window_seconds)
        rolling = self.get_rolling_averages()
        workers = self.get_worker_breakdown(window_seconds)
        priorities = self.get_priority_distribution(window_seconds)
        endpoints = self.get_endpoint_breakdown(window_seconds)
        
        return {
            "timestamp": datetime.now().isoformat(),
            "current_zone": self.current_zone,
            "rpm_current": rpm,
            "rolling_averages": rolling,
            "worker_breakdown": workers,
            "priority_distribution": priorities,
            "top_endpoints": endpoints,
            "total_calls_in_window": sum(workers.values()),
            "zone_transitions_count": len(self.zone_history),
            "last_zone_transition": self.zone_history[-1] if self.zone_history else None
        }
    
    def get_health_status(self) -> Dict:
        """Get health status for monitoring"""
        rpm_1min = self.get_rpm(60)
        rpm_5min = self.get_rpm(300)
        
        # Determine health
        if rpm_1min >= 39:
            health = "CRITICAL"
            message = f"Very high API usage: {rpm_1min:.1f} RPM"
        elif rpm_1min >= 35:
            health = "WARNING"
            message = f"High API usage: {rpm_1min:.1f} RPM"
        elif rpm_1min >= 30:
            health = "CAUTION"
            message = f"Elevated API usage: {rpm_1min:.1f} RPM"
        else:
            health = "OK"
            message = f"Normal API usage: {rpm_1min:.1f} RPM"
        
        return {
            "health": health,
            "message": message,
            "rpm_1min": rpm_1min,
            "rpm_5min": rpm_5min,
            "zone": self.current_zone,
            "timestamp": datetime.now().isoformat()
        }


# Global tracker instance
_tracker: Optional[APICallTracker] = None

def init_tracker(history_minutes: int = 15) -> APICallTracker:
    """Initialize global tracker instance"""
    global _tracker
    _tracker = APICallTracker(history_minutes=history_minutes)
    return _tracker

def get_tracker() -> APICallTracker:
    """Get global tracker instance"""
    global _tracker
    if _tracker is None:
        _tracker = init_tracker()
    return _tracker
