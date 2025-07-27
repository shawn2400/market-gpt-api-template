# scanner_utils.py

from binance.client import Client
import pandas as pd
import numpy as np
from ta.trend import EMAIndicator, MACD, ADXIndicator
from ta.momentum import RSIIndicator
from ta.volatility import BollingerBands
from ta.volume import OnBalanceVolumeIndicator
import os
import datetime

BINANCE_API_KEY = os.getenv("BINANCE_API_KEY")
BINANCE_SECRET_KEY = os.getenv("BINANCE_SECRET_KEY")

client = Client(BINANCE_API_KEY, BINANCE_SECRET_KEY)

def get_futures_symbols():
    exchange_info = client.futures_exchange_info()
    return [s['symbol'] for s in exchange_info['symbols'] if s['contractType'] == 'PERPETUAL']

def fetch_klines(symbol, interval='15m', limit=100):
    klines = client.futures_klines(symbol=symbol, interval=interval, limit=limit)
    df = pd.DataFrame(klines, columns=[
        "timestamp", "open", "high", "low", "close", "volume",
        "close_time", "quote_asset_volume", "num_trades",
        "taker_buy_base_vol", "taker_buy_quote_vol", "ignore"])
    df["close"] = pd.to_numeric(df["close"])
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit='ms')
    return df

def analyze_indicators(df):
    df['ema_21'] = EMAIndicator(df['close'], window=21).ema_indicator()
    df['ema_50'] = EMAIndicator(df['close'], window=50).ema_indicator()
    df['macd'] = MACD(df['close']).macd_diff()
    df['rsi'] = RSIIndicator(df['close']).rsi()
    df['adx'] = ADXIndicator(df['high'], df['low'], df['close']).adx()
    df['bb_bbm'] = BollingerBands(df['close']).bollinger_mavg()
    df['obv'] = OnBalanceVolumeIndicator(df['close'], df['volume']).on_balance_volume()
    return df

def filter_trade_signal(df):
    latest = df.iloc[-1]
    if latest['rsi'] < 30 and latest['macd'] > 0 and latest['close'] > latest['ema_21'] and latest['adx'] > 20:
        return "LONG"
    elif latest['rsi'] > 70 and latest['macd'] < 0 and latest['close'] < latest['ema_21'] and latest['adx'] > 20:
        return "SHORT"
    return None

def scan_market():
    results = []
    symbols = get_futures_symbols()
    for symbol in symbols:
        try:
            df = fetch_klines(symbol)
            df = analyze_indicators(df)
            signal = filter_trade_signal(df)
            if signal:
                results.append({"symbol": symbol, "signal": signal})
        except Exception as e:
            print(f"Error scanning {symbol}: {e}")
    return results

