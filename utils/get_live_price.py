# utils/get_live_price.py
from utils.binance_client import client

def get_price(symbol: str) -> float:
    """
    Fetch the current live price for the given symbol using the Binance API client.
    """
    ticker = client.get_symbol_ticker(symbol=symbol)
    return float(ticker['price'])
