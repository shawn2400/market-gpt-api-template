# utils/binance_client.py
import os
import logging
from binance.client import Client

BINANCE_API_KEY = os.getenv("BINANCE_API_KEY", "").strip()
BINANCE_API_SECRET = os.getenv("BINANCE_API_SECRET", "").strip()

if not BINANCE_API_KEY or not BINANCE_API_SECRET:
    logging.warning("⚠️ Missing Binance API credentials — live trading will fail!")

class BinanceClient:
    def __init__(self):
        self.client = Client(
            api_key=BINANCE_API_KEY,
            api_secret=BINANCE_API_SECRET
        )

    # === Spot ===
    def get_spot_balance(self, asset="USDT"):
        return self.client.get_asset_balance(asset=asset)

    # === Futures ===
    def get_futures_balance(self):
        return self.client.futures_account_balance()

    def futures_create_order(self, **kwargs):
        return self.client.futures_create_order(**kwargs)

    def futures_get_position(self, symbol="BTCUSDT"):
        return self.client.futures_position_information(symbol=symbol)

# ✅ instance מוכן לייבוא
binance_client = BinanceClient()




































