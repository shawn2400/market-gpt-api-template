import asyncio
import aiohttp
import time
from binance import AsyncClient
import os
from dotenv import load_dotenv

load_dotenv()
API_KEY = os.getenv("BINANCE_API_KEY")
API_SECRET = os.getenv("BINANCE_API_SECRET")

MAX_RETRIES = 3
SYMBOL_LIMIT = 300

async def fetch_futures_symbols():
    client = await AsyncClient.create(API_KEY, API_SECRET)
    exchange_info = await client.futures_exchange_info()
    await client.close_connection()
    return [
        symbol["symbol"]
        for symbol in exchange_info["symbols"]
        if symbol["contractType"] == "PERPETUAL" and symbol["status"] == "TRADING"
    ][:SYMBOL_LIMIT]

async def fetch_symbol_data(session, symbol):
    url = f"https://fapi.binance.com/fapi/v1/ticker/24hr?symbol={symbol}"
    for attempt in range(MAX_RETRIES):
        try:
            async with session.get(url, timeout=10) as response:
                response.raise_for_status()
                return await response.json()
        except aiohttp.ClientResponseError as e:
            print(f"⚠️ שגיאה ({e.status}) על {symbol} | ניסיון {attempt+1}")
            if e.status in [429, 418]:
                print("⏳ חסימה זמנית – ממתין 10 שניות")
                await asyncio.sleep(10)
            elif e.status >= 500:
                print("🛠 שגיאת שרת – ננסה שוב")
                await asyncio.sleep(2)
            else:
                break
        except Exception as e:
            print(f"❌ שגיאה כללית על {symbol}:", str(e))
            await asyncio.sleep(1)
    return None

async def scan_all_futures():
    symbols = await fetch_futures_symbols()
    print(f"🔍 סורק {len(symbols)} מטבעות Futures מ-Binance")

    async with aiohttp.ClientSession() as session:
        tasks = [fetch_symbol_data(session, symbol) for symbol in symbols]
        results = await asyncio.gather(*tasks)

    valid_results = [res for res in results if res]
    print(f"✅ נמצאו {len(valid_results)} סמלים תקינים מתוך {len(symbols)}")

    return valid_results
























