# scanner_utils.py

import pandas as pd
from binance.client import Client
from ta.momentum import RSIIndicator
from ta.volatility import BollingerBands
from ta.trend import MACD, EMAIndicator, ADXIndicator
from ta.volume import OnBalanceVolumeIndicator

client = None  # צריך להכניס את המפתח החי


def init_client(api_key, api_secret):
    global client
    client = Client(api_key, api_secret)


def get_futures_symbols():
    info = client.futures_exchange_info()
    return [s["symbol"] for s in info["symbols"] if s["contractType"] == "PERPETUAL" and s["quoteAsset"] == "USDT"]


def fetch_klines(symbol, interval="15m", limit=100):
    klines = client.futures_klines(symbol=symbol, interval=interval, limit=limit)
    df = pd.DataFrame(klines, columns=[
        "timestamp", "open", "high", "low", "close", "volume",
        "close_time", "quote_asset_volume", "num_trades",
        "taker_buy_base", "taker_buy_quote", "ignore"
    ])
    df["close"] = pd.to_numeric(df["close"])
    df["high"] = pd.to_numeric(df["high"])
    df["low"] = pd.to_numeric(df["low"])
    return df


def calculate_indicators(df):
    rsi = RSIIndicator(df["close"]).rsi()
    bb = BollingerBands(df["close"])
    macd = MACD(df["close"]).macd_diff()
    ema9 = EMAIndicator(df["close"], window=9).ema_indicator()
    ema21 = EMAIndicator(df["close"], window=21).ema_indicator()
    adx = ADXIndicator(df["high"], df["low"], df["close"]).adx()
    obv = OnBalanceVolumeIndicator(close=df["close"], volume=df["volume"].astype(float)).on_balance_volume()

    return {
        "rsi": rsi.iloc[-1],
        "bb_high": bb.bollinger_hband().iloc[-1],
        "bb_low": bb.bollinger_lband().iloc[-1],
        "macd": macd.iloc[-1],
        "ema9": ema9.iloc[-1],
        "ema21": ema21.iloc[-1],
        "adx": adx.iloc[-1],
        "obv": obv.iloc[-1],
    }


def scan_symbol(symbol):
    try:
        df = fetch_klines(symbol)
        indicators = calculate_indicators(df)
        return {
            "symbol": symbol,
            "rsi": indicators["rsi"],
            "macd": indicators["macd"],
            "adx": indicators["adx"],
            "bb_high": indicators["bb_high"],
            "bb_low": indicators["bb_low"],
            "ema9": indicators["ema9"],
            "ema21": indicators["ema21"],
            "obv": indicators["obv"]
        }
    except Exception as e:
        return {"symbol": symbol, "error": str(e)}
