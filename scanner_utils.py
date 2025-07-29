# scanner_utils.py – גרסה משודרגת עם טיפול ב־GPT Rate Limit ותמיכה בפרמטרים דינמיים

import asyncio
import aiohttp
import pandas as pd
from binance import AsyncClient
import os
from dotenv import load_dotenv
import logging
from utils.quality_score import compute_quality_score
from ai_analysis import analyze_with_ai
from indicators_utils import compute_indicators
from snapshot_utils import save_trade_snapshot
import matplotlib.pyplot as plt

load_dotenv()
API_KEY = os.getenv("BINANCE_API_KEY")
API_SECRET = os.getenv("BINANCE_API_SECRET")

# הגדרות ברירת מחדל
DEFAULT_INTERVAL = "1m"
SYMBOL_LIMIT = 300
CANDLE_LIMIT = 100
MIN_VOLUME = 10_000_000
MIN_VOLATILITY_PERCENT = 2.0
MIN_QUALITY_SCORE = int(os.getenv("MIN_QUALITY_SCORE", 5))

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
async def fetch_historical_klines(session, symbol, interval=DEFAULT_INTERVAL, limit=CANDLE_LIMIT):
    url = f"https://fapi.binance.com/fapi/v1/klines?symbol={symbol}&interval={interval}&limit={limit}"
    for _ in range(3):
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
            logging.warning(f"[!] נסיון כושל ({symbol}): {e}")
    return None

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
    entry = last['close']
    sl = entry - atr * 2 if signal == "LONG" else entry + atr * 2
    tp = entry + atr * 3 if signal == "LONG" else entry - atr * 3

    direction = signal
    quality_score = compute_quality_score(kline_df)
    if quality_score < MIN_QUALITY_SCORE:
        return None

    # חיזוי AI – מוגן מ־Rate Limit
    try:
        ai_analysis = analyze_with_ai({
            "rsi": round(last['rsi'], 2),
            "adx": round(last['adx'], 2),
            "trend": signal,
            "volume": round(last['volume'], 2),
            "pattern": "N/A"
        })
        ai_result = ai_analysis.get("analysis", "N/A")
    except Exception as e:
        logging.warning(f"[!] שגיאה ב־AI עבור {symbol}: {e}")
        ai_result = "N/A"

    # צילום snapshot
    snapshot_path = save_trade_snapshot({
        "symbol": symbol,
        "entry": entry,
        "stop": sl,
        "tp": tp,
        "direction": direction
    })

    # שמירת גרף
    try:
        os.makedirs("static", exist_ok=True)
        plt.figure(figsize=(6, 4))
        plt.plot(kline_df['timestamp'][-20:], kline_df['close'][-20:], marker='o', linestyle='-', label='Close')
        plt.title(f"📈 {symbol} Snapshot")
        plt.xlabel("Time")
        plt.ylabel("Price")
        plt.grid(True)
        plt.legend()
        plt.tight_layout()
        chart_path = f"static/{symbol}_chart.png"
        plt.savefig(chart_path)
        plt.close()
    except Exception as e:
        logging.warning(f"[!] שגיאה ביצירת גרף עבור {symbol}: {e}")
        chart_path = None

    return {
        "symbol": symbol,
        "entry": round(entry, 4),
        "stop": round(sl, 4),
        "tp": round(tp, 4),
        "direction": direction,
        "price_now": round(entry, 4),
        "rsi": round(last['rsi'], 2),
        "adx": round(last['adx'], 2),
        "atr": round(atr, 4),
        "macd_hist": round(last['macd_hist'], 4),
        "stoch_k": round(last['stoch_k'], 2),
        "volume": round(last['volume'], 2),
        "signal": signal,
        "quality_score": quality_score,
        "ai_analysis": ai_result,
        "snapshot": snapshot_path,
        "chart": chart_path
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































