from binance.client import Client
import os

api_key = os.getenv("BINANCE_API_KEY")
api_secret = os.getenv("BINANCE_API_SECRET")
client = Client(api_key, api_secret)

def scan_all_futures():
    symbols = [
        s["symbol"] for s in client.futures_exchange_info()["symbols"]
        if "USDT" in s["symbol"] and s["contractType"] == "PERPETUAL"
    ]

    results = []
    for symbol in symbols:
        try:
            klines = client.futures_klines(symbol=symbol, interval=Client.KLINE_INTERVAL_15MINUTE, limit=100)
            closes = [float(k[4]) for k in klines]
            volume = float(klines[-1][5])
            if closes[-1] > closes[-2] and volume > 100000:  # תנאי פשוט
                results.append({
                    "symbol": symbol,
                    "last_price": closes[-1],
                    "volume": volume,
                    "direction": "LONG"
                })
        except Exception:
            continue

    return sorted(results, key=lambda x: x["volume"], reverse=True)

