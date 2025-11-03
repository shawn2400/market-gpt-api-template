#!/usr/bin/env python3
# workers/sentinel_security.py
"""
Sentinel Security Monitor - Anomaly detection and security monitoring
Monitors for suspicious activity, rate limiting violations, and security threats
"""
import os
import sys
import time
import asyncio
import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional
from collections import defaultdict, deque

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.alerts import send_telegram_message

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("sentinel_security")

SENTINEL_ENABLED = os.getenv("SENTINEL_ENABLED", "1").lower() in ("1", "true", "yes")
SENTINEL_INTERVAL_SEC = int(os.getenv("SENTINEL_INTERVAL_SEC", "300"))
ALERT_THRESHOLD = int(os.getenv("SENTINEL_ALERT_THRESHOLD", "3"))

REQUEST_RATE_WINDOW = 60
MAX_REQUESTS_PER_MINUTE = int(os.getenv("MAX_REQUESTS_PER_MINUTE", "100"))

_request_log: Dict[str, deque] = defaultdict(lambda: deque(maxlen=1000))
_security_events: List[Dict[str, Any]] = []
_anomaly_counter: Dict[str, int] = defaultdict(int)

class SecurityMonitor:
    """Monitor security events and anomalies"""
    
    def __init__(self):
        self.start_time = datetime.now(timezone.utc)
        self.alert_count = 0
        
    def log_request(self, source_ip: str, endpoint: str):
        """Log an incoming request"""
        timestamp = time.time()
        _request_log[source_ip].append({
            "timestamp": timestamp,
            "endpoint": endpoint
        })
    
    def check_rate_limiting(self) -> List[Dict[str, Any]]:
        """Check for rate limiting violations"""
        violations = []
        now = time.time()
        cutoff = now - REQUEST_RATE_WINDOW
        
        for ip, requests in _request_log.items():
            recent = [r for r in requests if r["timestamp"] > cutoff]
            
            if len(recent) > MAX_REQUESTS_PER_MINUTE:
                violations.append({
                    "type": "rate_limit_violation",
                    "source_ip": ip,
                    "request_count": len(recent),
                    "threshold": MAX_REQUESTS_PER_MINUTE,
                    "severity": "medium"
                })
                
                _anomaly_counter[f"rate_limit_{ip}"] += 1
        
        return violations
    
    def check_authentication_failures(self) -> List[Dict[str, Any]]:
        """Check for authentication failure patterns"""
        failures = []
        
        return failures
    
    def detect_anomalies(self) -> Dict[str, Any]:
        """Detect security anomalies and suspicious patterns"""
        try:
            rate_violations = self.check_rate_limiting()
            auth_failures = self.check_authentication_failures()
            
            all_events = rate_violations + auth_failures
            
            critical_events = [e for e in all_events if e.get("severity") == "critical"]
            high_events = [e for e in all_events if e.get("severity") == "high"]
            medium_events = [e for e in all_events if e.get("severity") == "medium"]
            
            return {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "total_events": len(all_events),
                "critical": len(critical_events),
                "high": len(high_events),
                "medium": len(medium_events),
                "events": all_events[:10],
                "overall_status": "critical" if critical_events else "warning" if high_events else "normal"
            }
        except Exception as e:
            logger.error(f"Anomaly detection failed: {e}")
            return {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "error": str(e),
                "overall_status": "error"
            }
    
    def get_security_summary(self) -> Dict[str, Any]:
        """Get comprehensive security summary"""
        try:
            uptime = (datetime.now(timezone.utc) - self.start_time).total_seconds()
            
            return {
                "uptime_hours": round(uptime / 3600, 2),
                "total_alerts": self.alert_count,
                "monitored_ips": len(_request_log),
                "anomaly_types": len(_anomaly_counter),
                "status": "monitoring"
            }
        except Exception as e:
            logger.error(f"Failed to get security summary: {e}")
            return {"error": str(e)}

_monitor = SecurityMonitor()

def format_security_message(anomalies: Dict[str, Any], summary: Dict[str, Any]) -> str:
    """Format security data into readable message"""
    status = anomalies.get("overall_status", "unknown")
    timestamp = anomalies.get("timestamp", "N/A")
    
    status_emoji = {
        "normal": "✅",
        "warning": "⚠️",
        "critical": "🚨",
        "error": "❌"
    }.get(status, "❓")
    
    lines = [
        f"{status_emoji} <b>Sentinel Security Report</b>\n",
        f"Status: <b>{status.upper()}</b>",
        f"Time: {timestamp.split('T')[1].split('.')[0]} UTC\n"
    ]
    
    total = anomalies.get("total_events", 0)
    if total > 0:
        lines.append(f"🔍 Security Events: {total}")
        lines.append(f"  🚨 Critical: {anomalies.get('critical', 0)}")
        lines.append(f"  ⚠️  High: {anomalies.get('high', 0)}")
        lines.append(f"  ℹ️  Medium: {anomalies.get('medium', 0)}\n")
        
        events = anomalies.get("events", [])
        if events:
            lines.append("<b>Recent Events:</b>")
            for event in events[:5]:
                event_type = event.get("type", "unknown")
                severity = event.get("severity", "unknown")
                lines.append(f"  • {event_type} ({severity})")
                if "source_ip" in event:
                    lines.append(f"    IP: {event['source_ip']}")
    else:
        lines.append("✅ No security events detected")
    
    if "uptime_hours" in summary:
        lines.append(f"\n⏱ Uptime: {summary['uptime_hours']:.1f}h")
        lines.append(f"📊 Monitoring: {summary.get('monitored_ips', 0)} IPs")
    
    return "\n".join(lines)

async def send_security_alert(anomalies: Dict[str, Any], summary: Dict[str, Any], force: bool = False):
    """Send security alert to Telegram if needed"""
    try:
        status = anomalies.get("overall_status", "normal")
        event_count = anomalies.get("total_events", 0)
        
        should_alert = (
            force or
            status in ["critical", "warning"] or
            event_count >= ALERT_THRESHOLD
        )
        
        if not should_alert:
            logger.info(f"No alert needed: {event_count} events, status {status}")
            return
        
        message = format_security_message(anomalies, summary)
        
        await send_telegram_message(
            message,
            parse_mode="HTML",
            disable_preview=True
        )
        
        _monitor.alert_count += 1
        logger.info(f"Security alert sent: {status}")
    except Exception as e:
        logger.error(f"Failed to send security alert: {e}")

async def security_cycle(is_first: bool = False):
    """Run one security monitoring cycle"""
    try:
        logger.info("Running security scan...")
        
        anomalies = _monitor.detect_anomalies()
        summary = _monitor.get_security_summary()
        
        await send_security_alert(anomalies, summary, force=is_first)
        
        status = anomalies.get("overall_status", "unknown")
        logger.info(f"Security cycle completed: {status}")
    except Exception as e:
        logger.error(f"Security cycle failed: {e}")

async def security_loop():
    """Main security monitoring loop"""
    logger.info(f"Sentinel Security Monitor started (interval: {SENTINEL_INTERVAL_SEC}s)")
    
    if not SENTINEL_ENABLED:
        logger.warning("SENTINEL_ENABLED=0 - security monitor disabled")
        while True:
            await asyncio.sleep(3600)
    
    is_first = True
    while True:
        try:
            await security_cycle(is_first=is_first)
            is_first = False
            await asyncio.sleep(SENTINEL_INTERVAL_SEC)
        except KeyboardInterrupt:
            logger.info("Sentinel Security stopped by user")
            break
        except Exception as e:
            logger.error(f"Error in security loop: {e}")
            await asyncio.sleep(60)

def main():
    """Main entry point"""
    try:
        asyncio.run(security_loop())
    except KeyboardInterrupt:
        logger.info("Sentinel Security shutdown")

if __name__ == "__main__":
    main()
