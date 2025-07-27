import os
import pandas as pd
from binance.client import Client
from dotenv import load_dotenv
from ta.momentum import RSIIndicator
from ta.trend import EMAIndicator, MACD, ADXIndicator
import logging

load_dotenv()

# חיבור ל־Binance Futures
api_key = os.getenv("BINANCE_API_KEY")
api_secret = os.getenv("BINANCE_API_SECRET")
client = Client(api_key, api_secret)

def scan_all_futures(min_adx=17, min_volume=100_000):
    results = []
    try:
        # שליפת כל הסימבולים מסוג USDT perpetual
        exchange_info = client.futures_exchange_info()
        symbols = [
            s["symbol"] for s in exchange_info["symbols"]
            if "USDT" in s["symbol"] and s["contractType"] == "PERPETUAL"
        ]
        logging.info(f"📄 נסרקו {len(symbols)} זוגות PERPETUAL")

        for symbol in symbols:
            try:
                klines = client.futures_klines(
                    symbol=symbol,
                    interval=Client.KLINE_INTERVAL_15MINUTE,
                    limit=100
                )

                df = pd.DataFrame(klines, columns=[
                    "open_time", "open", "high", "low", "close", "volume",
                    "close_time", "quote_asset_volume", "number_of_trades",
                    "taker_buy_base", "taker_buy_quote", "ignore"
                ])

                # המרות טיפוסים
                df["close"] = df["close"].astype(float)
                df["high"] = df["high"].astype(float)
                df["low"] = df["low"].astype(float)
                df["volume"] = df["volume"].astype(float)

                if df.shape[0] < 50:
                    continue

                # אינדיקטורים
                rsi = RSIIndicator(df["close"]).rsi().iloc[-1]
                macd = MACD(df["close"]).macd_diff().iloc[-1]
                ema21 = EMAIndicator(df["close"], window=21).ema_indicator().iloc[-1]
                adx = ADXIndicator(df["high"], df["low"], df["close"]).adx().iloc[-1]
                price = df["close"].iloc[-1]
                volume = df["volume"].iloc[-1]

                # תנאי סינון — LONG בלבד לפי הכללים
                if (
                    rsi < 35 and
                    macd > 0 and
                    price > ema21 and
                    adx > min_adx and
                    volume > min_volume
                ):
                    result = {
                        "symbol": symbol,
                        "last_price": round(price, 4),
                        "volume": int(volume),
                        "rsi": round(rsi, 2),
                        "macd": round(macd, 4),
                        "adx": round(adx, 2),
                        "direction": "LONG"
                    }
                    logging.info(f"🟢 נמצא טרייד: {symbol} | מחיר {price} | RSI {rsi:.2f} | ADX {adx:.2f}")
                    results.append(result)

            except Exception as e:
                logging.warning(f"⚠️ שגיאה בעיבוד {symbol}: {e}")
                continue

    except Exception as e:
        logging.error(f"❌ שגיאה בשליפת מידע מ־Binance: {e}")
        return []

    return sorted(results, key=lambda x: x["volume"], reverse=True)



