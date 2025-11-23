"""
🔐 Plugin Registry v10.0 — OFFICIAL 6 Integrations Only

Supported integrations:
1. Binance API (primary execution)
2. Bybit API (backup execution)
3. 3Commas API (SmartTrade engine)
4. Cryptohopper API (scan + signals)
5. WunderTrading API (cross-exchange signals)
6. TradingView Webhooks (alerts feed)

❌ REMOVED (not supported):
- HyperTrader, Pionex, Bitsgap, Coinrule, Kryll, Stoic.ai, ProfitTrailer
"""

# ✅ OFFICIAL 6 INTEGRATIONS ONLY
AVAILABLE_PLUGINS = {
    # === SCANS ===
    "cryptohopper": {
        "client": "external.cryptohopper_client.CryptohopperClient",
        "type": "scanner",
        "api_type": "official",
        "required_env": ["CRYPTOHOPPER_API_KEY"],
        "timeout_sec": 2,
        "free_capabilities": {"scans": 30, "speed": "normal", "history": 24},
        "paid_capabilities": {"scans": 300, "speed": "high", "history": 90}
    },
    
    # === POSITION MANAGEMENT ===
    "3commas": {
        "client": "external.threecommas_client.ThreeCommasClient",
        "type": "manager",
        "api_type": "official",
        "required_env": ["THREECOMMAS_API_KEY", "THREECOMMAS_API_SECRET"],
        "timeout_sec": 2,
        "free_capabilities": {"smarttrade": False, "webhooks": 1},
        "paid_capabilities": {"smarttrade": True, "webhooks": 30}
    },
    
    # === SIGNALS ===
    "wunder": {
        "client": "external.wunder_client.WunderClient",
        "type": "signals",
        "api_type": "official",
        "required_env": ["WUNDER_API_KEY"],
        "timeout_sec": 2,
        "free_capabilities": {"webhooks": 1, "speed": "low"},
        "paid_capabilities": {"webhooks": 20, "speed": "high"}
    },
    
    "bybit_signals": {
        "client": "external.bybit_signals.BybitSignals",
        "type": "futures_signals",
        "api_type": "official",
        "required_env": ["BYBIT_API_KEY", "BYBIT_API_SECRET"],
        "timeout_sec": 2,
        "free_capabilities": {"signals": "basic", "coverage": 100},
        "paid_capabilities": {"signals": "pro", "coverage": 500}
    },
    
    "tradingview": {
        "client": "external.tradingview_handler.TVWebhookHandler",
        "type": "indicators",
        "api_type": "official",
        "required_env": ["TV_WEBHOOK_SECRET"],
        "timeout_sec": 2,
        "free_capabilities": {"pinescript": "limited", "webhooks": 1},
        "paid_capabilities": {"pinescript": "unlimited", "webhooks": 50}
    },
    
    # === EXECUTION ===
    "bybit_execution": {
        "client": "external.bybit_execution.BybitExecutor",
        "type": "execution",
        "api_type": "official",
        "required_env": ["BYBIT_API_KEY", "BYBIT_API_SECRET"],
        "timeout_sec": 2,
        "priority": 2,
        "free_capabilities": {"latency": "normal", "orders": 10},
        "paid_capabilities": {"latency": "fast", "orders": 100}
    },
}

# 🚫 REMOVED (not supported)
UNSUPPORTED_PLUGINS = {
    "hyper": "❌ HyperTrader - NOT SUPPORTED",
    "pionex": "❌ Pionex - NOT SUPPORTED",
    "bitsgap": "❌ Bitsgap - NOT SUPPORTED",
    "coinrule": "❌ Coinrule - NOT SUPPORTED",
    "kryll": "❌ Kryll - NOT SUPPORTED",
    "stoic": "❌ Stoic.ai - NOT SUPPORTED",
    "profittrailer": "❌ ProfitTrailer - NOT SUPPORTED",
}

def get_plugin_config(name):
    """Get plugin config (OFFICIAL ONLY)"""
    if name in UNSUPPORTED_PLUGINS:
        raise ValueError(f"❌ {UNSUPPORTED_PLUGINS[name]}")
    return AVAILABLE_PLUGINS.get(name)

def list_plugins():
    """List all available plugins (OFFICIAL ONLY)"""
    return list(AVAILABLE_PLUGINS.keys())

def get_plugins_by_type(ptype):
    """Get plugins by type (scanner, manager, signals, etc)"""
    return [name for name, cfg in AVAILABLE_PLUGINS.items() if cfg["type"] == ptype]

def is_official_plugin(name: str) -> bool:
    """Check if plugin is official"""
    return name in AVAILABLE_PLUGINS

def get_required_env(name: str) -> list:
    """Get required environment variables for plugin"""
    cfg = AVAILABLE_PLUGINS.get(name)
    return cfg.get("required_env", []) if cfg else []

def get_unsupported_error(name: str) -> str:
    """Get error message for unsupported plugin"""
    return UNSUPPORTED_PLUGINS.get(name, f"❌ Unknown plugin: {name}")
