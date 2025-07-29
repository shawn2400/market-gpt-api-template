from binance.client import Client
import os
import logging

API_KEY = os.getenv("BINANCE_API_KEY")
API_SECRET = os.getenv("BINANCE_API_SECRET")

client = None
if API_KEY and API_SECRET:
    client = Client(API_KEY, API_SECRET)
else:
    logging.warning("⚠️ Binance API keys missing in environment variables.")








