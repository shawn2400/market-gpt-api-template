"""
Test Capability Detector
"""
import pytest
import os
from algo_core.capability_detector import (
    detect_capabilities,
    is_paid,
    upgrade_plan,
    downgrade_plan
)

def test_free_plan_detection():
    """Test free plan detection"""
    # Clear env
    if "PAID_CRYPTOHOPPER" in os.environ:
        del os.environ["PAID_CRYPTOHOPPER"]
    
    cfg = {
        "free_capabilities": {"scans": 30},
        "paid_capabilities": {"scans": 300}
    }
    
    cap = detect_capabilities("cryptohopper", cfg)
    assert cap["scans"] == 30

def test_paid_plan_detection():
    """Test paid plan detection"""
    os.environ["PAID_CRYPTOHOPPER"] = "1"
    
    cfg = {
        "free_capabilities": {"scans": 30},
        "paid_capabilities": {"scans": 300}
    }
    
    cap = detect_capabilities("cryptohopper", cfg)
    assert cap["scans"] == 300
    
    # Cleanup
    if "PAID_CRYPTOHOPPER" in os.environ:
        del os.environ["PAID_CRYPTOHOPPER"]

def test_upgrade_downgrade():
    """Test plan upgrade/downgrade"""
    if "PAID_TEST_BOT" in os.environ:
        del os.environ["PAID_TEST_BOT"]
    
    assert not is_paid("test_bot")
    
    upgrade_plan("test_bot")
    assert is_paid("test_bot")
    
    downgrade_plan("test_bot")
    assert not is_paid("test_bot")
