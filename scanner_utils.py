import asyncio
import aiohttp
import time
import pandas as pd
from binance import AsyncClient
import os
from dotenv import load_dotenv
from ta.trend import EMAIndicator, MACD, ADXIndicator
from ta.momentum import RSIIndicator, StochasticOscillator
from ta.volatility import AverageTrueRange, BollingerBands

load_dotenv()
API_KEY = os.getenv("BINANCE_API_KEY")
API_SECRET = os.getenv("BINANCE_API_SECRET")

MAX_RETRIES = 3
SYMBOL_LIMIT = 300
CANDLE_LIMIT = 100

def calculate_obv(df):
    obv = [0]
    for i in range(1, len(df)):
        if df['close'].iloc[i] > df['close'].iloc[i-1]:
            obv.append(obv[-1] + df['volume'].iloc[i])
        elif df['close'].iloc[i] < df['close'].iloc[i-1]:
            obv.append(obv[-1] - df['volume'].iloc[i])
        else:
            obv.append(obv[-1])
    df['obv'] = obv
    df['obv_trend'] = df['obv'].diff() > 0
    return df

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

async def fetch_historical_klines(session, symbol, interval="1m", limit=CANDLE_LIMIT):
    url = f"https://fapi.binance.com/fapi/v1/klines?symbol={symbol}&interval={interval}&limit={limit}"
    try:
        async with session.get(url, timeout=10) as response:
            response.raise_for_status()
            data = await response.json()
            df = pd.DataFrame(data, columns=[
                'timestamp', 'open', 'high', 'low', 'close', 'volume',
                'close_time', 'quote_asset_volume', 'number_of_trades',
                'taker_buy_base_volume', 'taker_buy_quote_volume', 'ignore'])
            df = df[['timestamp', 'open', 'high', 'low', 'close', 'volume']].astype(float)
            return df
    except Exception as e:
        print(f"[!] שגיאה בהורדת נתונים עבור {symbol}: {e}")
        return None

async def scan_all_futures():
    symbols = await fetch_futures_symbols()
    print(f"🔍 סורק {len(symbols)} מטבעות Futures מ-Binance")

    async with aiohttp.ClientSession() as session:
        tasks = [fetch_symbol_data(session, symbol) for symbol in symbols]
        raw_results = await asyncio.gather(*tasks)

        # סינון סמלים עם תנועה חזקה בלבד (volume גבוה + תנועה משמעותית)
        results = [res for res in raw_results if res and float(res.get("quoteVolume", 0)) > 10_000_000 and abs(float(res.get("priceChangePercent", 0))) > 2.0]

        print(f"✅ נמצאו {len(results)} סמלים בעלי תנועה חזקה מתוך {len(symbols)}")

        return results

























