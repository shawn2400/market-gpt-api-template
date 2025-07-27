import os
import time
import numpy as np
import pandas as pd
from binance.client import Client
from utils.quality_score import compute_quality_score  # לוודא שיש קובץ כזה
from ta.trend import EMAIndicator, MACD, ADXIndicator
from ta.momentum import RSIIndicator
from ta.volatility import AverageTrueRange

# התחברות ל־Binance
client = Client(
    api_key=os.getenv("BINANCE_API_KEY"),
    api_secret=os.getenv("BINANCE_API_SECRET")
)

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
    df['EMA21'] = EMAIndicator(df['close'], window=21).ema_indicator()
    df['EMA50'] = EMAIndicator(df['close'], window=50).ema_indicator()
    df['RSI'] = RSIIndicator(df['close'], window=14).rsi()
    macd = MACD(df['close'])
    df['MACD'] = macd.macd()
    df['MACD_signal'] = macd.macd_signal()
    df['ADX'] = ADXIndicator(df['high'], df['low'], df['close'], window=14).adx()
    df['ATR'] = AverageTrueRange(df['high'], df['low'], df['close'], window=14).average_true_range()
    return df

def is_volume_spike(df, threshold=1.8):
    last_vol = df['volume'].iloc[-1]
    avg_vol = df['volume'].iloc[:-1].mean()
    return last_vol > avg_vol * threshold

def scan_all_futures_live():
    results = []
    symbols = [s['symbol'] for s in client.futures_exchange_info()['symbols']
               if s['contractType'] == 'PERPETUAL' and s['quoteAsset'] == 'USDT']

    for symbol in symbols:
        klines = get_klines(symbol)
        if len(klines) < 50:
            continue

        df = pd.DataFrame(klines, columns=[
            'timestamp', 'open', 'high', 'low', 'close', 'volume',
            'close_time', 'qav', 'trades', 'tb_base', 'tb_quote', 'ignore'
        ])
        df[['open','high','low','close','volume']] = df[['open','high','low','close','volume']].astype(float)

        # הזרקת מחיר חי לנר האחרון
        live_price = get_live_price(symbol)
        if not live_price:
            continue
        df.at[df.index[-1], 'close'] = live_price

        df = calculate_indicators(df)

        # תנאי LONG:
        ema_cross = df['EMA21'].iloc[-2] < df['EMA50'].iloc[-2] and df['EMA21'].iloc[-1] > df['EMA50'].iloc[-1]
        macd_cross = df['MACD'].iloc[-2] < df['MACD_signal'].iloc[-2] and df['MACD'].iloc[-1] > df['MACD_signal'].iloc[-1]
        rsi_ok = df['RSI'].iloc[-1] > 50 and df['RSI'].iloc[-1] < 70
        adx_ok = df['ADX'].iloc[-1] > 17
        volume_ok = is_volume_spike(df)
        
        if all([ema_cross, macd_cross, rsi_ok, adx_ok, volume_ok]):
            score = compute_quality_score(df)
            if score >= 4:  # ציון איכות מינימלי
                results.append({
                    'symbol': symbol,
                    'price': live_price,
                    'signal': 'LONG',
                    'EMA21': df['EMA21'].iloc[-1],
                    'EMA50': df['EMA50'].iloc[-1],
                    'RSI': df['RSI'].iloc[-1],
                    'MACD': df['MACD'].iloc[-1],
                    'ADX': df['ADX'].iloc[-1],
                    'ATR': df['ATR'].iloc[-1],
                    'volume': df['volume'].iloc[-1],
                    'quality_score': score
                })

        time.sleep(0.05)  # מניעת rate-limit

    return results













