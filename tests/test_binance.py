from binance.client import Client

API_KEY = "RkctQeBjGDncg0UEgYKRaCQ5dWZZczqW8QIpEOYfbIFYgL0LFnWFD9wxSWGw7bDo"
API_SECRET = "9gpLTl4zAqxSUeiue5iiFSEYgpXYVu9ivnMFxVMOWEOGoBo0XpYbbYsuS3sU14qV"

client = Client(API_KEY, API_SECRET)
client.API_URL = "https://api1.binance.com/api"

try:
    client.ping()
    print("✅ Binance client connected (Spot + Futures)")
    price = client.get_symbol_ticker(symbol="BTCUSDT")
    print(f"BTC Price: {price['price']}")
except Exception as e:
    print(f"❌ Error connecting to Binance: {e}")
