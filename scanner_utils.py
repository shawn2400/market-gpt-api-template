# scanner_utils.py
import os
import requests
import pandas as pd
from ta.trend import EMAIndicator, MACD, ADXIndicator
from ta.momentum import RSIIndicator
from ta.volatility import AverageTrueRange
from utils.quality_score import compute_quality_score
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("BINANCE_API_KEY")
BASE_URL = "https://18.162.221.196"
HOST_HEADER = {"Host": "fapi.binance.com"}

# ✅ שליפת מחירי Futures

def get_futures_prices():
    url = f"{BASE_URL}/fapi/v1/ticker/price"
    headers = {"X-MBX-APIKEY": API_KEY, **HOST_HEADER}
    response = requests.get(url, headers=headers, timeout=10)
    response.raise_for_status()
    return response.json()

# ✅ שליפת נתוני קנדלים ל־symbol

def get_klines(symbol, interval="15m", limit=50):
    url = f"{BASE_URL}/fapi/v1/klines"
    params = {"symbol": symbol, "interval": interval, "limit": limit}
    headers = {"X-MBX-APIKEY": API_KEY, **HOST_HEADER}
    response = requests.get(url, headers=headers, params=params, timeout=10)
    response.raise_for_status()
    data = response.json()
    df = pd.DataFrame(data, columns=[
        "timestamp", "open", "high", "low", "close", "volume",
        "close_time", "quote_asset_volume", "number_of_trades",
        "taker_buy_base", "taker_buy_quote", "ignore"
    ])
    df = df.astype({"open": float, "high": float, "low": float, "close": float, "volume": float})
    return df

# ✅ סריקה חכמה עם דירוג איכות

def scan_all_futures():
    prices = get_futures_prices()
    results = []

    for item in prices:
        symbol = item["symbol"]
        if not symbol.endswith("USDT") or any(x in symbol for x in ["DOWN", "UP", "BULL", "BEAR"]):
            continue

        try:
            df = get_klines(symbol)
            df["ema_21"] = EMAIndicator(df["close"], window=21).ema_indicator()
            df["macd"] = MACD(df["close"]).macd_diff()
            df["rsi"] = RSIIndicator(df["close"]).rsi()
            df["adx"] = ADXIndicator(df["high"], df["low"], df["close"]).adx()
            df["atr"] = AverageTrueRange(df["high"], df["low"], df["close"]).average_true_range()
            df["volume_mean"] = df["volume"].rolling(20).mean()

            last_row = df.iloc[-1]
            score = compute_quality_score(last_row)

            if score >= 6:
                results.append({
                    "symbol": symbol,
                    "price": float(item["price"]),
                    "quality_score": score
                })
        except Exception as e:
            continue

    return sorted(results, key=lambda x: x["quality_score"], reverse=True)





