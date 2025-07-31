import asyncio
import json
import time
import aiohttp
import threading
import requests

prices = {}
ws_connected = False

def get_price(symbol: str) -> float:
    """
    מחזיר את המחיר האחרון של הסימבול, דרך WebSocket אם אפשר, ואם לא – דרך REST API.
    """
    symbol = symbol.lower()
    if symbol in prices and prices[symbol] > 0:
        return prices[symbol]
    try:
        url = f"https://fapi.binance.com/fapi/v1/ticker/price?symbol={symbol.upper()}"
        res = requests.get(url, timeout=5)
        return float(res.json()["price"])
    except Exception as e:
        print(f"[WS Fallback] ❌ שגיאה ב־REST API: {e}")
        return 0.0

def launch_websocket(symbols: list[str]):
    """
    משיק WebSocket חי ל־Binance עבור רשימת סימבולים. תוצאה מתעדכנת במילון prices.
    """
    def run_ws():
        global ws_connected
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(ws_loop(symbols))

    thread = threading.Thread(target=run_ws, daemon=True)
    thread.start()

async def ws_loop(symbols: list[str]):
    """
    לולאת WebSocket אסינכרונית – מאזינה לעדכונים חיים של סימבולים.
    """
    global ws_connected
    ws_connected = False

    stream_url = "wss://fstream.binance.com/stream?streams=" + "/".join(
        f"{symbol.lower()}@ticker" for symbol in symbols
    )

    try:
        async with aiohttp.ClientSession() as session:
            async with session.ws_connect(stream_url) as ws:
                ws_connected = True
                print(f"[WS] ✅ מחובר ל־Binance WebSocket עם {len(symbols)} זוגות")
                async for msg in ws:
                    if msg.type == aiohttp.WSMsgType.TEXT:
                        try:
                            data = json.loads(msg.data)
                            stream = data.get("stream", "")
                            payload = data.get("data", {})
                            symbol = payload.get("s", "").lower()
                            price = float(payload.get("c", 0))
                            if symbol and price > 0:
                                prices[symbol] = price
                        except Exception as e:
                            print(f"[WS] ⚠️ שגיאה בעיבוד הודעה: {e}")
                    elif msg.type in [aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR]:
                        print("[WS] ❌ החיבור נסגר או נכשל – מעבר ל־REST")
                        break
    except Exception as e:
        print(f"[WS] ❌ חיבור WebSocket נכשל: {e}")
    finally:
        ws_connected = False



