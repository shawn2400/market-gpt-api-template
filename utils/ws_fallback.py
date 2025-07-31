from utils.ws_fallback import launch_websocket, get_price
import time

symbol = "BTCUSDT"
launch_websocket(symbol)

for _ in range(10):
    price = get_price(symbol)
    print(f"Current {symbol} price: {price}")
    time.sleep(2)

