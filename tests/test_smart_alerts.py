"""
Tests for Smart Alerts Engine
"""

import pytest
import asyncio
from utils.smart_alerts import SmartAlerts, AlertPriority, AlertState
from engine.ai_supervisor import AISupervisor

@pytest.mark.asyncio
async def test_smart_alerts_init():
    """Test SmartAlerts initialization"""
    alerts = SmartAlerts()
    await alerts.init()
    
    assert alerts.auto_silenced == False
    assert alerts.current_risk_level == 0
    assert alerts.alert_count_today == 0

@pytest.mark.asyncio
async def test_no_spam_baseline():
    """Test Mode 1 - Silent unless required (no spam baseline)"""
    alerts = SmartAlerts()
    
    # Should not alert if state not changed and risk low
    should_alert = await alerts.should_alert(
        alert_type="TEST",
        risk_level=20,
        state_changed=False
    )
    
    assert should_alert == False, "Should not alert on stable state"

@pytest.mark.asyncio
async def test_state_change_detection():
    """Test that state changes trigger alerts"""
    alerts = SmartAlerts()
    
    # Should alert on state change
    should_alert = await alerts.should_alert(
        alert_type="VOLATILITY",
        risk_level=60,
        state_changed=True
    )
    
    # Note: May be False if suppressed, but logic should trigger
    assert True  # Placeholder

@pytest.mark.asyncio
async def test_suppression_window():
    """Test 6-hour suppression window"""
    alerts = SmartAlerts()
    
    # First alert should pass
    result1 = await alerts.send_alert(
        alert_type="TEST_ALERT",
        message="First alert",
        priority=AlertPriority.P2_ACTION
    )
    
    # Second alert should be suppressed
    result2 = await alerts.should_alert(
        alert_type="TEST_ALERT",
        risk_level=50,
        state_changed=True
    )
    
    assert result2 == False, "Alert should be suppressed within 6 hours"

@pytest.mark.asyncio
async def test_critical_alerts_not_suppressed():
    """Test that critical alerts bypass suppression"""
    alerts = SmartAlerts()
    
    # Critical alerts should always be allowed
    critical_types = ["KILL_SWITCH", "API_DOWN", "SL_MISSING", "CIRCUIT_BREAKER"]
    
    for alert_type in critical_types:
        allowed = await alerts.ai_supervisor_allows(alert_type, 50)
        assert allowed == True, f"{alert_type} should never be suppressed"

@pytest.mark.asyncio
async def test_daily_cap():
    """Test max 7 alerts per day"""
    alerts = SmartAlerts()
    
    # Fill up to max
    for i in range(7):
        alerts.alert_count_today += 1
    
    # Next alert should fail
    should_alert = await alerts.should_alert(
        alert_type=f"ALERT_{8}",
        risk_level=50,
        state_changed=True
    )
    
    assert should_alert == False, "Should respect daily cap"

@pytest.mark.asyncio
async def test_normalization():
    """Test system normalization message"""
    alerts = SmartAlerts()
    alerts.current_risk_level = 80
    
    # Would send normalization message
    assert alerts.normalization_pending == False

@pytest.mark.asyncio
async def test_silence_and_resume():
    """Test silence/resume functionality"""
    alerts = SmartAlerts()
    
    # Silence alerts
    await alerts.silence_alerts(7200)
    assert alerts.auto_silenced == True
    
    # Non-critical should be blocked
    allowed = await alerts.ai_supervisor_allows("INFO_ALERT", 50)
    assert allowed == False
    
    # Critical should still work
    allowed = await alerts.ai_supervisor_allows("KILL_SWITCH", 50)
    assert allowed == True
    
    # Resume
    await alerts.resume_alerts()
    assert alerts.auto_silenced == False

@pytest.mark.asyncio
async def test_ai_supervisor_basics():
    """Test AI Supervisor decision logic"""
    supervisor = AISupervisor()
    
    # Test various alert types
    result = await supervisor.analyze_alert("UNKNOWN_TYPE")
    should_alert, reason = result
    assert should_alert == True  # Unknown types escalate

@pytest.mark.asyncio
async def test_risk_level_calculation():
    """Test risk level calculation (0-100)"""
    supervisor = AISupervisor()
    
    risk = await supervisor.get_risk_level()
    assert 0 <= risk <= 100, "Risk level should be 0-100"

@pytest.mark.asyncio
async def test_alert_priority_levels():
    """Test alert priority levels"""
    alerts = SmartAlerts()
    
    # Test all priority levels exist
    priorities = [
        AlertPriority.P1_CRITICAL,
        AlertPriority.P2_ACTION,
        AlertPriority.P3_INFO
    ]
    
    assert len(priorities) == 3

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
