"""
Test External Bot Connectivity
"""
import pytest
import asyncio
from external.plugin_manager import PluginManager

@pytest.fixture
def plugin_manager():
    pm = PluginManager()
    pm.load_all()
    return pm

def test_all_plugins_loaded(plugin_manager):
    """Verify all 6 bots loaded successfully"""
    assert len(plugin_manager.plugins) == 6
    assert "cryptohopper" in plugin_manager.plugins
    assert "3commas" in plugin_manager.plugins
    assert "wunder" in plugin_manager.plugins
    assert "hyper" in plugin_manager.plugins
    assert "bybit_signals" in plugin_manager.plugins
    assert "tradingview" in plugin_manager.plugins

def test_plugin_status(plugin_manager):
    """Verify each plugin has get_status method"""
    for name, plugin in plugin_manager.plugins.items():
        status = plugin.get_status()
        assert "name" in status
        assert "type" in status
        assert "enabled" in status
        assert "score" in status

def test_plugin_enable_disable(plugin_manager):
    """Verify enable/disable mechanism"""
    hopper = plugin_manager.get("cryptohopper")
    
    hopper.disable()
    assert not hopper.enabled
    
    hopper.enable()
    assert hopper.enabled

def test_plugin_scoring(plugin_manager):
    """Verify plugin scoring works (0-10)"""
    hopper = plugin_manager.get("cryptohopper")
    
    hopper.set_score(8.5)
    assert hopper.score == 8.5
    
    hopper.set_score(15)  # Should cap at 10
    assert hopper.score == 10
    
    hopper.set_score(-1)  # Should floor at 0
    assert hopper.score == 0

def test_plugin_manager_get_by_type(plugin_manager):
    """Verify get_by_type filters correctly"""
    scanners = plugin_manager.get_by_type("scanner")
    assert len(scanners) >= 1
    assert scanners[0].ptype == "scanner"
    
    managers = plugin_manager.get_by_type("manager")
    assert len(managers) >= 1
    assert managers[0].ptype == "manager"
