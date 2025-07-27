# scanner_utils.py

from binance.client import Client
from binance.exceptions import BinanceAPIException
from dotenv import load_dotenv
import os
import pandas as pd
import ta
import logging
from trade_executor import execute_trade_live
from utils.quantity_utils import auto_risk_allocation
from utils.quality_score import compute_quality_score
from utils.trade_storage import save_trade

load_dotenv()

api_key = os.getenv("BINANCE_API_KEY")
api_secret = os.getenv("BINANCE_API_SECRET")
client = Client(api_key, api_secret)

TOP_SYMBOLS = [
    "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT",
    "DOGEUSDT", "ADAUSDT", "AVAXUSDT", "LINKUSDT", "MATICUSDT",
    "LTCUSDT", "DOTUSDT", "TRXUSDT", "APTUSDT", "OPUSDT",
    "RNDRUSDT", "INJUSDT", "ARBUSDT", "SEIUSDT", "TONUSDT",
    "PEPEUSDT", "JASMYUSDT", "GALAUSDT", "BLZUSDT", "SUIUSDT"
]

def fetch_klines(symbol, interval='15m', limit=100):
    try:
        klines = client.futures_klines(symbol=symbol, interval=interval, limit=limit)
        df = pd.DataFrame(klines, columns=[
            'timestamp', 'open', 'high', 'low', 'close',
            'volume', 'close_time', 'quote_asset_volume',
            'number_of_trades', 'taker_buy_base', 'taker_buy_quote', 'ignore']
        )
        df['close'] = df['close'].astype(float)
        df['high'] = df['high'].astype(float)
        df['low'] = df['low'].astype(float)
        df['volume'] = df['volume'].astype(float)
        return df
    except BinanceAPIException as e:
        logging.error(f"[fetch_klines] Error fetching klines for {symbol}: {e}")
        return None

def scan_all_futures():
    results = []

    for symbol in TOP_SYMBOLS:
        df = fetch_klines(symbol)
        if df is None or df.empty:
            continue

        try:
            df['rsi'] = ta.momentum.RSIIndicator(df['close']).rsi()
            df['macd'] = ta.trend.MACD(df['close']).macd()
            df['ema21'] = ta.trend.EMAIndicator(df['close'], 21).ema_indicator()
            df['adx'] = ta.trend.ADXIndicator(df['high'], df['low'], df['close']).adx()
        except Exception as e:
            logging.warning(f"[scan] אינדיקטור נכשל עבור {symbol}: {e}")
            continue

        last = df.iloc[-1]
        prev = df.iloc[-2]

        if (
            last['rsi'] > 55 and
            last['macd'] > 0 and
            last['close'] > last['ema21'] and
            last['adx'] > 17 and
            last['volume'] > prev['volume'] * 1.3
        ):
            entry = round(last['close'], 4)
            stop = round(entry * 0.97, 4)
            tp = round(entry * 1.05, 4)
            leverage = 20
            budget = 100
            confidence = 90

            df['atr'] = ta.volatility.AverageTrueRange(df['high'], df['low'], df['close']).average_true_range()
            quality = compute_quality_score(df.iloc[-1])

            if quality < 4:
                continue

            try:
                capital = auto_risk_allocation(entry, stop, budget)
                result = execute_trade_live(
                    symbol=symbol,
                    entry=entry,
                    stop=stop,
                    tp=tp,
                    direction="LONG",
                    leverage=leverage,
                    budget_usd=capital,
                    use_grid=True
                )

                save_trade({
                    "symbol": symbol,
                    "entry": entry,
                    "stop": stop,
                    "tp": tp,
                    "direction": "LONG",
                    "leverage": leverage,
                    "confidence": confidence,
                    "quality_score": quality,
                    "type": "GRID"
                })

                return {
                    "executed_trade": {
                        "symbol": symbol,
                        "entry": entry,
                        "stop": stop,
                        "tp": tp,
                        "leverage": leverage,
                        "direction": "LONG",
                        "confidence": confidence,
                        "quality_score": quality
                    },
                    "all_candidates": results
                }
            except Exception as e:
                logging.error(f"[scan_all_futures] שגיאה בהפעלה ל־{symbol}: {e}")
                continue
        else:
            results.append({
                "symbol": symbol,
                "entry": round(last['close'], 4),
                "rsi": round(last['rsi'], 2),
                "macd": round(last['macd'], 4),
                "ema21": round(last['ema21'], 4),
                "adx": round(last['adx'], 2),
                "volume": round(last['volume'], 2)
            })

    return {"executed_trade": None, "all_candidates": results}











