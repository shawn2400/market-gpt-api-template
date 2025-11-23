"""
🚫 HyperTrader Client — DEPRECATED v10.0

❌ NOT SUPPORTED IN v10.0+
This integration has been removed. Only official 6 integrations supported:
1. Binance API
2. Bybit API
3. 3Commas API
4. Cryptohopper API
5. WunderTrading API
6. TradingView Webhooks

If you were using this, please migrate to one of the supported integrations.
"""

import logging

logger = logging.getLogger("algogpt.hyper_client")

class HyperTraderClient:
    """DEPRECATED - Use official integrations instead"""
    
    def __init__(self, capabilities=None):
        raise NotImplementedError(
            "❌ HyperTrader is NOT SUPPORTED in v10.0+\n"
            "Use one of the 6 official integrations:\n"
            "  1. Binance API\n"
            "  2. Bybit API\n"
            "  3. 3Commas API\n"
            "  4. Cryptohopper API\n"
            "  5. WunderTrading API\n"
            "  6. TradingView Webhooks"
        )
