"""
Plugin Registry — Centralized bot configuration
"""

AVAILABLE_PLUGINS = {
    "cryptohopper": {
        "client": "external.cryptohopper_client.CryptohopperClient",
        "type": "scanner",
        "free_capabilities": {"scans": 30, "speed": "normal", "history": 24},
        "paid_capabilities": {"scans": 300, "speed": "high", "history": 90}
    },
    "3commas": {
        "client": "external.threecommas_client.ThreeCommasClient",
        "type": "manager",
        "free_capabilities": {"smarttrade": False, "webhooks": 1},
        "paid_capabilities": {"smarttrade": True, "webhooks": 30}
    },
    "wunder": {
        "client": "external.wunder_client.WunderClient",
        "type": "signals",
        "free_capabilities": {"webhooks": 1, "speed": "low"},
        "paid_capabilities": {"webhooks": 20, "speed": "high"}
    },
    "hyper": {
        "client": "external.hyper_client.HyperTraderClient",
        "type": "execution",
        "free_capabilities": {"latency": "normal", "orders": 10},
        "paid_capabilities": {"latency": "fast", "orders": 100}
    },
    "bybit_signals": {
        "client": "external.bybit_signals.BybitSignals",
        "type": "futures_signals",
        "free_capabilities": {"signals": "basic", "coverage": 100},
        "paid_capabilities": {"signals": "pro", "coverage": 500}
    },
    "tradingview": {
        "client": "external.tradingview_handler.TVWebhookHandler",
        "type": "indicators",
        "free_capabilities": {"pinescript": "limited", "webhooks": 1},
        "paid_capabilities": {"pinescript": "unlimited", "webhooks": 50}
    }
}

def get_plugin_config(name):
    """Get plugin config"""
    return AVAILABLE_PLUGINS.get(name)

def list_plugins():
    """List all available plugins"""
    return list(AVAILABLE_PLUGINS.keys())

def get_plugins_by_type(ptype):
    """Get plugins by type (scanner, manager, signals, etc)"""
    return [name for name, cfg in AVAILABLE_PLUGINS.items() if cfg["type"] == ptype]
