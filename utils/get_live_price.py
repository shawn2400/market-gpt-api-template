from utils.binance_client import client

def get_live_price(symbol):
    try:
        data = client.futures_symbol_ticker(symbol=symbol)
        return float(data['price'])
    except:
        return None
