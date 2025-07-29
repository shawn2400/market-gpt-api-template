# scanner_utils.py – גרסה משודרגת תואמת auto_executor

import asyncio
import aiohttp
import pandas as pd
from binance import AsyncClient
import os
from dotenv import load_dotenv
from ta.trend import EMAIndicator, MACD, ADXIndicator
from ta.momentum import RSIIndicator, StochasticOscillator
from ta.volatility import AverageTrueRange
import logging
from utils.quality_score import compute_quality_score

load_dotenv()
API_KEY = os.getenv("BINANCE_API_KEY")
API_SECRET = os.getenv("BINANCE_API_SECRET")

# הגדרות
MAX_RETRIES = 3
SYMBOL_LIMIT = 300
CANDLE_LIMIT = 100
MIN_VOLUME = 10_000_000
MIN_VOLATILITY_PERCENT = 2.0

# === חישוב OBV ===
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

# === סמלים של Binance Futures ===
async def fetch_futures_symbols():
    try:
        client = await AsyncClient.create(API_KEY, API_SECRET)
        exchange_info = await client.futures_exchange_info()
        await client.close_connection()
        return [
            s["symbol"] for s in exchange_info["symbols"]
            if s["contractType"] == "PERPETUAL" and s["status"] == "TRADING"
        ][:SYMBOL_LIMIT]
    except Exception as e:
        logging.error(f"[!] שגיאה בהבאת סמלים: {e}")
        return []

# === נתוני נרות ===
async def fetch_historical_klines(session, symbol, interval="1m", limit=CANDLE_LIMIT):
    url = f"https://fapi.binance.com/fapi/v1/klines?symbol={symbol}&interval={interval}&limit={limit}"
    for _ in range(MAX_RETRIES):
        try:
            async with session.get(url, timeout=10) as response:
                response.raise_for_status()
                data = await response.json()
                df = pd.DataFrame(data, columns=[
                    'timestamp', 'open', 'high', 'low', 'close', 'volume',
                    'close_time', 'quote_asset_volume', 'number_of_trades',
                    'taker_buy_base_volume', 'taker_buy_quote_volume', 'ignore'
                ])
                df = df[['timestamp', 'open', 'high', 'low', 'close', 'volume']].astype(float)
                return df
        except Exception as e:
            logging.warning(f"[!] ניסיון כושל ({symbol}): {e}")
    return None

# === אינדיקטורים טכניים ===
def compute_indicators(df):
    try:
        df['ema_21'] = EMAIndicator(df['close'], window=21).ema_indicator()
        df['ema_50'] = EMAIndicator(df['close'], window=50).ema_indicator()
        df['rsi'] = RSIIndicator(df['close']).rsi()
        macd = MACD(df['close'])
        df['macd_hist'] = macd.macd_diff()
        df['adx'] = ADXIndicator(df['high'], df['low'], df['close']).adx()
        df['atr'] = AverageTrueRange(df['high'], df['low'], df['close']).average_true_range()
        stoch = StochasticOscillator(df['high'], df['low'], df['close'])
        df['stoch_k'] = stoch.stoch()
        df['stoch_d'] = stoch.stoch_signal()
        df['volume_mean'] = df['volume'].rolling(window=20).mean()
        df = calculate_obv(df)
        df.dropna(inplace=True)
        return df
    except Exception as e:
        logging.error(f"[!] שגיאה באינדיקטורים: {e}")
        return df

# === ניתוח סמל בודד ===
async def fetch_symbol_analysis(session, symbol):
    kline_df = await fetch_historical_klines(session, symbol)
    if kline_df is None or len(kline_df) < 30:
        return None

    kline_df = compute_indicators(kline_df)
    last = kline_df.iloc[-1]

    signal = None
    if (
        last['rsi'] < 30 and last['macd_hist'] > 0 and last['close'] > last['ema_21']
        and last['adx'] > 17 and last['volume'] > last['volume_mean'] * 1.3
    ):
        signal = "LONG"
    elif (
        last['rsi'] > 70 and last['macd_hist'] < 0 and last['close'] < last['ema_21']
        and last['adx'] > 17 and not last['obv_trend']
    ):
        signal = "SHORT"

    if not signal:
        return None

    # חישוב SL/TP לפי ATR
    atr = last['atr']
    entry_price = last['close']
    sl = entry_price - atr * 2 if signal == "LONG" else entry_price + atr * 2
    tp = entry_price + atr * 3 if signal == "LONG" else entry_price - atr * 3

    direction = signal
    quality_score = compute_quality_score(kline_df)

    return {
        "symbol": symbol,
        "entry_price": round(entry_price, 4),
        "sl": round(sl, 4),
        "tp": round(tp, 4),
        "direction": direction,
        "price": round(entry_price, 4),
        "rsi": round(last['rsi'], 2),
        "adx": round(last['adx'], 2),
        "atr": round(atr, 4),
        "macd_hist": round(last['macd_hist'], 4),
        "stoch_k": round(last['stoch_k'], 2),
        "volume": round(last['volume'], 2),
        "signal": signal,
        "quality_score": quality_score
    }

# === סריקה חיה מלאה ===
async def scan_all_futures():
    symbols = await fetch_futures_symbols()
    if not symbols:
        logging.warning("[!] לא נמצאו סמלים לסריקה.")
        return []

    logging.info(f"🔍 סריקה על {len(symbols)} מטבעות מ-Binance Futures")

    async with aiohttp.ClientSession() as session:
        tasks = [fetch_symbol_analysis(session, symbol) for symbol in symbols]
        results = await asyncio.gather(*tasks)
        valid = [r for r in results if r]

    logging.info(f"✅ נמצאו {len(valid)} טריידים פוטנציאליים מתוך {len(symbols)}")
    return valid





























