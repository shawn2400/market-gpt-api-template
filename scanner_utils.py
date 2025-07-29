# scan_futures_market.py

import asyncio
from aiohttp import web, ClientSession
import numpy as np
import pandas as pd
import ta
import os
import logging

logging.basicConfig(level=logging.INFO)

BINANCE_FAPI_URL = "https://fapi.binance.com"

async def fetch_klines(symbol, interval="15m", limit=100):
    """
    שולף נתוני נרות פיוצ'רס מ-Binance (async).
    """
    url = f"{BINANCE_FAPI_URL}/fapi/v1/klines?symbol={symbol}&interval={interval}&limit={limit}"
    async with ClientSession() as session:
        async with session.get(url, timeout=7) as resp:
            if resp.status != 200:
                raise Exception(f"Failed to fetch klines for {symbol}: {resp.status}")
            raw = await resp.json()
            df = pd.DataFrame(raw, columns=[
                'timestamp','open','high','low','close','volume','close_time',
                'quote_asset_volume','number_of_trades','taker_buy_base_volume',
                'taker_buy_quote_volume','ignore'
            ])
            df = df[['open', 'high', 'low', 'close', 'volume']].astype(float)
            return df

async def fetch_top_symbols(limit=20):
    """
    מחזיר את המטבעות עם הנפח הגבוה ביותר (פיוצ'רס)
    """
    url = f"{BINANCE_FAPI_URL}/fapi/v1/ticker/24hr"
    async with ClientSession() as session:
        async with session.get(url, timeout=7) as resp:
            data = await resp.json()
            top = sorted(data, key=lambda x: float(x['quoteVolume']), reverse=True)
            return [d['symbol'] for d in top[:limit]]

async def analyze_symbol(symbol):
    """
    מחשב אינדיקטורים (RSI, ADX) על הנתונים העדכניים ומחזיר המלצה
    """
    try:
        df = await fetch_klines(symbol)
        if len(df) < 30:
            return None  # Not enough data
        df['rsi'] = ta.momentum.RSIIndicator(close=df['close'], window=14).rsi()
        adx = ta.trend.ADXIndicator(high=df['high'], low=df['low'], close=df['close'])
        df['adx'] = adx.adx()
        last = df.iloc[-1]
        direction = "LONG" if last['rsi'] < 35 and last['adx'] > 20 else \
                    "SHORT" if last['rsi'] > 70 and last['adx'] > 20 else "NEUTRAL"
        return {
            'symbol': symbol,
            'close': float(last['close']),
            'volume': float(last['volume']),
            'rsi': round(float(last['rsi']), 2),
            'adx': round(float(last['adx']), 2),
            'direction': direction
        }
    except Exception as e:
        logging.warning(f"[{symbol}] error: {e}")
        return None

async def fetch_binance_futures_data(limit=15):
    """
    סורק את המטבעות הכי נזילים ומחזיר רשימה עם RSI/ADX/המלצה
    """
    symbols = await fetch_top_symbols(limit)
    tasks = [analyze_symbol(symbol) for symbol in symbols]
    results = await asyncio.gather(*tasks)
    return [r for r in results if r is not None]

async def scan_futures_market(request):
    """
    נקודת קצה ל-API: שלח בקשת GET ל-/scan_futures_market וקבל תוצאה חיה
    """
    try:
        results = await fetch_binance_futures_data(limit=15)
        return web.json_response({'results': results})
    except Exception as e:
        logging.error(f"Scan error: {e}")
        return web.json_response({'error': str(e)}, status=500)

def create_app():
    app = web.Application()
    app.router.add_get('/scan_futures_market', scan_futures_market)
    return app

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    logging.info(f"🚀 Starting server on port {port}")
    web.run_app(create_app(), port=port)


































