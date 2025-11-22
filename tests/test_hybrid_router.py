"""
Test Hybrid Router
"""
import pytest
import asyncio
from external.plugin_manager import PluginManager
from algo_core.hybrid_router import HybridRouter

@pytest.fixture
def setup():
    pm = PluginManager()
    pm.load_all()
    router = HybridRouter(pm)
    return router, pm

@pytest.mark.asyncio
async def test_get_scans(setup):
    """Test getting scans from scanner bots"""
    router, _ = setup
    scans = await router.get_scans()
    assert isinstance(scans, list)

@pytest.mark.asyncio
async def test_get_signals(setup):
    """Test getting signals from signal bots"""
    router, _ = setup
    signals = await router.get_signals()
    assert isinstance(signals, list)

@pytest.mark.asyncio
async def test_execute_order(setup):
    """Test order execution with failover"""
    router, _ = setup
    
    order = {
        "symbol": "BTCUSDT",
        "sl": 100,
        "tp": 200
    }
    
    result = await router.execute_order(order)
    assert isinstance(result, dict)
    # Should have either a result or error
    assert "error" in result or "status" in result or "result" in result

@pytest.mark.asyncio
async def test_failover_if_hyper_disabled(setup):
    """Test failover when HyperTrader is disabled"""
    router, pm = setup
    
    hyper = pm.get("hyper")
    hyper.disable()
    
    order = {"symbol": "ETHUSDT", "sl": 50, "tp": 150}
    result = await router.execute_order(order)
    
    # Should still return result (fallback to 3commas or error)
    assert isinstance(result, dict)
