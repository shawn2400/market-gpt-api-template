from binance.client import Client
import os
import pandas as pd
from ta.momentum import RSIIndicator
from ta.trend import EMAIndicator, MACD, ADXIndicator
from dotenv import load_dotenv

load_dotenv()

# Binance API init
api_key = os.getenv("BINANCE_API_KEY")
api_secret = os.getenv("BINANCE_API_SECRET")
client = Client(api_key, api_secret)

def scan_all_futures():
    try:
        symbols = [
            s["symbol"] for s in client.futures_exchange_info()["symbols"]
            if "USDT" in s["symbol"] and s["contractType"] == "PERPETUAL"
        ]
    except Exception as e:
        print("⚠️ שגיאה בשליפת רשימת סימבולים:", e)
        return []

    results = []
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

            df["close"] = df["close"].astype(float)
            df["high"] = df["high"].astype(float)
            df["low"] = df["low"].astype(float)
            df["volume"] = df["volume"].astype(float)

            if df.shape[0] < 50:
                continue

            # Indicators
            rsi = RSIIndicator(df["close"]).rsi().iloc[-1]
            macd = MACD(df["close"]).macd_diff().iloc[-1]
            ema21 = EMAIndicator(df["close"], window=21).ema_indicator().iloc[-1]
            adx = ADXIndicator(df["high"], df["low"], df["close"]).adx().iloc[-1]
            price = df["close"].iloc[-1]
            volume = df["volume"].iloc[-1]

            # Filter conditions
            if (
                rsi < 35 and
                macd > 0 and
                price > ema21 and
                adx > 17 and
                volume > 100_000
            ):
                results.append({
                    "symbol": symbol,
                    "last_price": price,
                    "volume": volume,
                    "rsi": round(rsi, 2),
                    "adx": round(adx, 2),
                    "direction": "LONG"
                })

        except Exception as e:
            print(f"⚠️ שגיאה בעיבוד סימבול {symbol}: {e}")
            continue

    return sorted(results, key=lambda x: x["volume"], reverse=True)


