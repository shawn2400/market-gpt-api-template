"""
Smart Alerts API Routes
"""

from fastapi import APIRouter, Depends, HTTPException
from typing import Dict, List, Optional
from utils.smart_alerts import get_smart_alerts, SmartAlerts, AlertPriority
from engine.ai_supervisor import get_ai_supervisor
import redis.asyncio as redis

router = APIRouter(prefix="/system/alerts", tags=["alerts"])

async def get_redis() -> Optional[redis.Redis]:
    """Get Redis connection"""
    # TODO: Get from app context
    return None

@router.get("/state")
async def get_alerts_state(
    smart_alerts: SmartAlerts = Depends(get_smart_alerts)
) -> Dict:
    """Get current alert state"""
    return await smart_alerts.get_status()

@router.get("/risk")
async def get_risk_level(
    supervisor = Depends(get_ai_supervisor)
) -> Dict:
    """Get current risk level (0-100)"""
    risk = await supervisor.get_risk_level()
    return {
        'risk_level': risk,
        'status': 'OK' if risk < 50 else 'WARNING' if risk < 75 else 'CRITICAL'
    }

@router.get("/history")
async def get_alerts_history(
    limit: int = 20,
    smart_alerts: SmartAlerts = Depends(get_smart_alerts)
) -> Dict:
    """Get alert history"""
    history = await smart_alerts.get_history(limit)
    return {
        'alerts': history,
        'count': len(history)
    }

@router.post("/test")
async def test_alert(
    alert_type: str,
    message: str,
    priority: str = "P2",
    risk_level: int = 50,
    smart_alerts: SmartAlerts = Depends(get_smart_alerts)
) -> Dict:
    """Test alert (admin-only, for debugging)"""
    
    priority_map = {
        'P1': AlertPriority.P1_CRITICAL,
        'P2': AlertPriority.P2_ACTION,
        'P3': AlertPriority.P3_INFO
    }
    
    alert_priority = priority_map.get(priority, AlertPriority.P2_ACTION)
    sent = await smart_alerts.send_alert(alert_type, message, alert_priority, risk_level)
    
    return {
        'alert_sent': sent,
        'alert_type': alert_type,
        'priority': priority
    }

@router.post("/silence")
async def silence_alerts(
    duration_sec: int = 7200,
    smart_alerts: SmartAlerts = Depends(get_smart_alerts)
) -> Dict:
    """Silence non-critical alerts for X seconds"""
    
    await smart_alerts.silence_alerts(duration_sec)
    return {
        'status': 'silenced',
        'duration_sec': duration_sec
    }

@router.post("/resume")
async def resume_alerts(
    smart_alerts: SmartAlerts = Depends(get_smart_alerts)
) -> Dict:
    """Resume normal alerting"""
    
    await smart_alerts.resume_alerts()
    return {'status': 'resumed'}
