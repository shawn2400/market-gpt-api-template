from binance.client import Client
from binance.enums import *
import numpy as np
import pandas as pd
import time

client = Client(api_key=API_KEY, api_secret=API_SECRET)

def get_live_price(symbol):
    try:
        return float(client.futures_symbol_ticker(symbol=symbol)['price'])
    except:
        return None

def get_klines(symbol, interval='1m', limit=100):
    try:
        return client.futures_klines(symbol=symbol, interval=interval, limit=limit)
    except:
        return []

def calculate_indicators(df):
    df['EMA21'] = df['close'].ewm(span=21).mean()
    df['EMA50'] = df['close'].ewm(span=50).mean()
    delta = df['close'].diff()
    gain = delta.where(delta > 0, 0)
    loss = -delta.where(delta < 0, 0)
    avg_gain = gain.rolling(14).mean()
    avg_loss = loss.rolling(14).mean()
    rs = avg_gain / avg_loss
    df['RSI'] = 100 - (100 / (1 + rs))
    return df

def scan_all_futures():
    results = []
    exchange_info = client.futures_exchange_info()
    symbols = [s['symbol'] for s in exchange_info['symbols'] if s['contractType'] == 'PERPETUAL' and s['quoteAsset'] == 'USDT']

    for symbol in symbols:
        klines = get_klines(symbol)
        if len(klines) < 50:
            continue

        df = pd.DataFrame(klines, columns=['timestamp','open','high','low','close','volume','close_time','quote_asset_volume','trades','taker_buy_base','taker_buy_quote','ignore'])
        df['close'] = df['close'].astype(float)

        live_price = get_live_price(symbol)
        if not live_price:
            continue

        # החלפת המחיר האחרון במחיר חי!
        df.iloc[-1, df.columns.get_loc('close')] = live_price

        df = calculate_indicators(df)

        # תנאי לדוגמה: EMA21 חוצה את EMA50 מלמטה
        if df['EMA21'].iloc[-2] < df['EMA50'].iloc[-2] and df['EMA21'].iloc[-1] > df['EMA50'].iloc[-1]:
            rsi = df['RSI'].iloc[-1]
            if rsi < 70:  # רק אם RSI עדיין לא בשיא
                results.append({
                    'symbol': symbol,
                    'live_price': live_price,
                    'signal': 'LONG',
                    'EMA21': df['EMA21'].iloc[-1],
                    'EMA50': df['EMA50'].iloc[-1],
                    'RSI': rsi
                })

        time.sleep(0.05)  # למנוע rate limit

    return results












