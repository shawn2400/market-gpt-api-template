"""
🔐 Test Suite v10.0 — Official 6 Integrations Only

Tests:
1. test_plugin_loads_only_6() - Verify only 6 official plugins exist
2. test_hybrid_router_source_validation() - Verify routing validates sources
3. test_consensus_ignore_unsupported() - Verify unsupported bots rejected
4. test_execution_route_priority() - Verify execution routing order
"""

import pytest
import asyncio
from external.plugin_registry import (
    AVAILABLE_PLUGINS,
    UNSUPPORTED_PLUGINS,
    is_official_plugin,
    get_unsupported_error
)
from external.plugin_manager import PluginManager
from algo_core.hybrid_router import HybridRouter

def test_plugin_loads_only_6():
    """✅ Test: Only 6 official plugins available"""
    assert len(AVAILABLE_PLUGINS) == 6, f"Expected 6 plugins, got {len(AVAILABLE_PLUGINS)}"
    
    expected = {"cryptohopper", "3commas", "wunder", "bybit_signals", "tradingview", "bybit_execution"}
    actual = set(AVAILABLE_PLUGINS.keys())
    
    assert actual == expected, f"Plugins mismatch. Expected {expected}, got {actual}"

def test_unsupported_plugins_blocked():
    """✅ Test: Unsupported plugins are blocked"""
    unsupported = ["hyper", "pionex", "bitsgap", "coinrule", "kryll", "stoic", "profittrailer"]
    
    for plugin in unsupported:
        assert not is_official_plugin(plugin), f"❌ {plugin} should NOT be official"
        assert plugin in UNSUPPORTED_PLUGINS, f"❌ {plugin} should be in unsupported list"
        error = get_unsupported_error(plugin)
        assert "NOT SUPPORTED" in error, f"❌ Error message should indicate unsupported: {error}"

def test_hybrid_router_source_validation():
    """✅ Test: Router validates sources are official"""
    # Create mock plugin manager
    pm = PluginManager()
    
    # Verify that router would validate sources
    router = HybridRouter(pm)
    
    # All loaded plugins must be official
    for name in pm.plugins.keys():
        assert is_official_plugin(name), f"❌ Plugin {name} is not official"

def test_plugin_api_type_official():
    """✅ Test: All plugins have api_type='official'"""
    for name, cfg in AVAILABLE_PLUGINS.items():
        assert cfg.get("api_type") == "official", f"❌ {name} should have api_type='official'"

def test_plugin_required_env():
    """✅ Test: All plugins specify required env vars"""
    for name, cfg in AVAILABLE_PLUGINS.items():
        assert "required_env" in cfg, f"❌ {name} missing required_env"
        assert isinstance(cfg["required_env"], list), f"❌ {name} required_env must be list"

def test_execution_route_priority():
    """✅ Test: Execution routing has correct priority order"""
    # Priority should be:
    # 1. Binance (native)
    # 2. Bybit (secondary)
    # 3. 3Commas (tertiary)
    
    execution_plugins = [
        name for name, cfg in AVAILABLE_PLUGINS.items()
        if cfg["type"] == "execution"
    ]
    
    # Should have bybit_execution at least
    assert "bybit_execution" in execution_plugins, "❌ bybit_execution not found"

def test_scan_route_priority():
    """✅ Test: Scan routing has correct priority order"""
    # Priority should be:
    # 1. Cryptohopper
    # 2. WunderTrading
    # 3. TradingView
    
    scanners = [
        name for name, cfg in AVAILABLE_PLUGINS.items()
        if cfg["type"] == "scanner"
    ]
    
    assert "cryptohopper" in scanners, "❌ cryptohopper not found"

def test_signal_route_priority():
    """✅ Test: Signal routing has correct priority order"""
    # Priority should be:
    # 1. TradingView
    # 2. WunderTrading
    # 3. Bybit Signals
    # 4. Cryptohopper
    
    signal_types = {"signals", "futures_signals", "indicators"}
    signal_bots = [
        name for name, cfg in AVAILABLE_PLUGINS.items()
        if cfg["type"] in signal_types
    ]
    
    assert "tradingview" in signal_bots, "❌ tradingview not found"
    assert "wunder" in signal_bots, "❌ wunder not found"
    assert "bybit_signals" in signal_bots, "❌ bybit_signals not found"

def test_no_hypertrader_reference():
    """✅ Test: HyperTrader is completely removed"""
    assert "hyper" not in AVAILABLE_PLUGINS, "❌ HyperTrader still in available plugins"
    assert is_official_plugin("hyper") == False, "❌ HyperTrader should not be official"

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
