# utils/binance_client.py
from binance.client import Client
import os

API_KEY = os.getenv("BINANCE_API_KEY")
API_SECRET = os.getenv("BINANCE_API_SECRET")

client = None
if API_KEY and API_SECRET:
    client = Client(API_KEY, API_SECRET)
else:
    print("⚠️ Binance API keys missing in environment variables.")


# utils/get_klines.py
import pandas as pd
import logging
from time import sleep
from utils.binance_client import client

def get_klines(
    symbol: str,
    interval: str = '15m',
    limit: int = 500,
    market_type: str = "futures",
    grid_base_type: str = "futures",
    start_time: int = None,
    end_time: int = None,
    retries: int = 3
) -> pd.DataFrame:
    if not client:
        logging.error("⚠️ Binance client not initialized.")
        return pd.DataFrame()

    mt = market_type
    if market_type == "grid":
        mt = grid_base_type if grid_base_type in ("futures", "spot") else "futures"

    for attempt in range(retries):
        try:
            if mt == "futures":
                raw = client.futures_klines(
                    symbol=symbol,
                    interval=interval,
                    limit=limit,
                    startTime=start_time,
                    endTime=end_time
                )
            elif mt == "spot":
                raw = client.get_klines(
                    symbol=symbol,
                    interval=interval,
                    limit=limit,
                    startTime=start_time,
                    endTime=end_time
                )
            else:
                logging.error(f"Unsupported market_type: {mt}")
                return pd.DataFrame()

            if not raw:
                logging.warning(f"No raw Klines data for {symbol} on {mt}, attempt {attempt+1}")
                sleep(1)
                continue

            df = pd.DataFrame(raw, columns=[
                'timestamp', 'open', 'high', 'low', 'close', 'volume',
                'close_time', 'quote_asset_volume', 'number_of_trades',
                'taker_buy_base_volume', 'taker_buy_quote_volume', 'ignore'
            ])
            df = df[['timestamp', 'open', 'high', 'low', 'close', 'volume']]
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            df[['open', 'high', 'low', 'close', 'volume']] = df[['open', 'high', 'low', 'close', 'volume']].astype(float)

            logging.info(f"Got {len(df)} klines for {symbol} ({mt}) on attempt {attempt+1}")
            return df

        except Exception as e:
            logging.warning(f"Error fetching klines for {symbol} attempt {attempt+1}: {e}")
            sleep(1)

    logging.error(f"Failed to fetch klines for {symbol} after {retries} attempts")
    return pd.DataFrame()


# utils/indicators.py
import ta
import pandas as pd
import numpy as np
import logging

def supertrend(df, period=10, multiplier=3):
    hl2 = (df['high'] + df['low']) / 2
    atr = ta.volatility.AverageTrueRange(high=df['high'], low=df['low'], close=df['close'], window=period).average_true_range()
    upperband = hl2 + (multiplier * atr)
    lowerband = hl2 - (multiplier * atr)
    final_upperband = upperband.copy()
    final_lowerband = lowerband.copy()
    supertrend = [np.nan] * len(df)
    direction = [1] * len(df)
    for i in range(1, len(df)):
        if df['close'].iloc[i] > final_upperband.iloc[i-1]:
            direction[i] = 1
        elif df['close'].iloc[i] < final_lowerband.iloc[i-1]:
            direction[i] = -1
        else:
            direction[i] = direction[i-1]
            if direction[i] == 1 and final_lowerband.iloc[i] < final_lowerband.iloc[i-1]:
                final_lowerband.iloc[i] = final_lowerband.iloc[i-1]
            if direction[i] == -1 and final_upperband.iloc[i] > final_upperband.iloc[i-1]:
                final_upperband.iloc[i] = final_upperband.iloc[i-1]
        supertrend[i] = final_lowerband.iloc[i] if direction[i] == 1 else final_upperband.iloc[i]
    df['supertrend'] = supertrend
    df['supertrend_dir'] = direction
    return df

def compute_indicators(df, volume_window=20):
    # בדיקה בסיסית
    if df.empty or any(col not in df.columns for col in ['open','high','low','close','volume']):
        logging.warning("[indicators] DataFrame invalid or missing columns for indicator calculation")
        return df

    try:
        # חישוב אינדיקטורים
        df['ema_21'] = ta.trend.EMAIndicator(close=df['close'], window=21).ema_indicator()
        df['ema_50'] = ta.trend.EMAIndicator(close=df['close'], window=50).ema_indicator()
        df['ema_200'] = ta.trend.EMAIndicator(close=df['close'], window=200).ema_indicator()
        
        df['sma_50'] = ta.trend.SMAIndicator(close=df['close'], window=50).sma_indicator()
        df['sma_200'] = ta.trend.SMAIndicator(close=df['close'], window=200).sma_indicator()

        df['rsi'] = ta.momentum.RSIIndicator(close=df['close'], window=14).rsi()
        df['stoch_rsi'] = ta.momentum.StochRSIIndicator(close=df['close'], window=14).stochrsi()

        df['williams_r'] = ta.momentum.WilliamsRIndicator(
            high=df['high'], low=df['low'], close=df['close'], lbp=14).williams_r()

        macd = ta.trend.MACD(close=df['close'])
        df['macd'] = macd.macd()
        df['macd_signal'] = macd.macd_signal()
        df['macd_hist'] = macd.macd_diff()

        df['adx'] = ta.trend.ADXIndicator(high=df['high'], low=df['low'], close=df['close']).adx()

        df['atr'] = ta.volatility.AverageTrueRange(high=df['high'], low=df['low'], close=df['close']).average_true_range()

        stoch = ta.momentum.StochasticOscillator(high=df['high'], low=df['low'], close=df['close'])
        df['stoch_k'] = stoch.stoch()
        df['stoch_d'] = stoch.stoch_signal()

        obv = ta.volume.OnBalanceVolumeIndicator(close=df['close'], volume=df['volume'])
        df['obv'] = obv.on_balance_volume()
        df['obv_trend'] = df['obv'].diff() > 0

        df['vwap'] = (df['close'] * df['volume']).cumsum() / df['volume'].cumsum()
        df['vwap_trend'] = df['close'] > df['vwap']

        df['volume_mean'] = df['volume'].rolling(window=volume_window).mean()
        df['volume_spike'] = df['volume'] > (df['volume_mean'] * 2)

        df['cci'] = ta.trend.CCIIndicator(high=df['high'], low=df['low'], close=df['close'], window=20).cci()

        bb = ta.volatility.BollingerBands(close=df['close'], window=20)
        df['bb_upper'] = bb.bollinger_hband()
        df['bb_lower'] = bb.bollinger_lband()
        df['bb_width'] = df['bb_upper'] - df['bb_lower']

        mfi = ta.volume.MFIIndicator(high=df['high'], low=df['low'], close=df['close'], volume=df['volume'])
        df['mfi'] = mfi.money_flow_index()

        df['is_doji'] = (abs(df['close'] - df['open']) / (df['high'] - df['low'] + 1e-6)) < 0.1

        df['grid_signal'] = ((df['rsi'] < 35) & (df['macd_hist'] > 0) & (df['adx'] > 17))

        df['tech_score'] = (
            (df['rsi'].between(45, 60)) * 1 +
            (df['adx'] > 20) * 1 +
            (df['macd_hist'] > 0) * 1 +
            (df['close'] > df['ema_21']) * 1
        )

        df = supertrend(df, period=10, multiplier=3)

        df['ema_cross_bull'] = (df['ema_21'] > df['ema_50']) & (df['ema_21'].shift(1) <= df['ema_50'].shift(1))
        df['ema_cross_bear'] = (df['ema_21'] < df['ema_50']) & (df['ema_21'].shift(1) >= df['ema_50'].shift(1))
        df['macd_cross_bull'] = (df['macd'] > df['macd_signal']) & (df['macd'].shift(1) <= df['macd_signal'].shift(1))
        df['macd_cross_bear'] = (df['macd'] < df['macd_signal']) & (df['macd'].shift(1) >= df['macd_signal'].shift(1))

        df['bullish_engulfing'] = (df['close'] > df['open']) & (df['open'].shift(1) > df['close'].shift(1)) & (df['close'] > df['open'].shift(1))
        df['bearish_engulfing'] = (df['close'] < df['open']) & (df['open'].shift(1) < df['close'].shift(1)) & (df['close'] < df['open'].shift(1))

        # עדיף להחליף dropna ב-fillna כדי לשמור על שורות
        df.fillna(method='ffill', inplace=True)
        df.fillna(method='bfill', inplace=True)

        return df

    except Exception as e:
        logging.error(f"[indicators] שגיאה בחישוב אינדיקטורים: {e}")
        return df


# utils/scanner_utils.py
import asyncio
import logging
from utils.get_klines import get_klines
from utils.indicators import compute_indicators

POPULAR_SYMBOLS = [
    "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "ADAUSDT",
    "XRPUSDT", "AVAXUSDT", "DOGEUSDT", "MATICUSDT", "LINKUSDT"
]

def compute_quality_score(last):
    score = 0
    if 45 < last.get("rsi", 0) < 65:
        score += 1
    if last.get("adx", 0) > 20:
        score += 1
    if last.get("macd_hist", 0) > 0:
        score += 1
    if last.get("close", 0) > last.get("ema_21", 0):
        score += 1
    if 30 < last.get("stoch_k", 0) < 70:
        score += 1
    if last.get("cci", 0) > 0:
        score += 1
    if last.get("vwap", 0) < last.get("close", 0):
        score += 1
    return score

async def analyze_symbol(symbol: str, interval: str = "15m", limit: int = 100):
    try:
        df = get_klines(symbol=symbol, interval=interval, limit=limit, market_type="futures")
        if df is None or df.empty or len(df) < 30:
            logging.warning(f"[{symbol}] אין מספיק נתונים לניתוח")
            return None

        df = compute_indicators(df)
        if df.empty or len(df) < 1:
            logging.warning(f"[{symbol}] אין נתונים לאחר חישוב אינדיקטורים")
            return None

        last = df.iloc[-1]

        direction = (
            "LONG" if last["rsi"] < 35 and last["adx"] > 20 and last["close"] > last["ema_21"]
            else "SHORT" if last["rsi"] > 70 and last["adx"] > 20 and last["close"] < last["ema_21"]
            else "NEUTRAL"
        )

        quality_score = compute_quality_score(last)

        return {
            "symbol": symbol,
            "close": float(last["close"]),
            "volume": float(last["volume"]),
            "rsi": round(float(last["rsi"]), 2),
            "adx": round(float(last["adx"]), 2),
            "macd": round(float(last["macd"]), 4),
            "macd_hist": round(float(last["macd_hist"]), 4),
            "ema_21": round(float(last["ema_21"]), 4),
            "ema_50": round(float(last["ema_50"]), 4),
            "vwap": round(float(last["vwap"]), 4),
            "bb_upper": round(float(last["bb_upper"]), 4),
            "bb_lower": round(float(last["bb_lower"]), 4),
            "stoch_k": round(float(last["stoch_k"]), 2),
            "stoch_d": round(float(last["stoch_d"]), 2),
            "obv": round(float(last["obv"]), 2),
            "cci": round(float(last["cci"]), 2),
            "mfi": round(float(last["mfi"]), 2),
            "atr": round(float(last["atr"]), 4),
            "direction": direction,
            "quality_score": int(quality_score)
        }
    except Exception as e:
        logging.warning(f"[{symbol}] analyze error: {e}")
        return None

async def scan_all(symbols: list = None, interval: str = "15m", limit: int = 100, min_quality: int = 5):
    if symbols is None:
        symbols = POPULAR_SYMBOLS

    tasks = [analyze_symbol(s, interval, limit) for s in symbols]
    results = await asyncio.gather(*tasks)

    filtered = [
        r for r in results if r and r["quality_score"] >= min_quality and r["direction"] in ("LONG", "SHORT")
    ]

    filtered = sorted(filtered, key=lambda x: (-x["quality_score"], -x["volume"]))
    return filtered


# auto_executor.py (פונקציית ריצה אוטומטית לדוגמה)
import asyncio
import logging
from utils.scanner_utils import scan_all
from utils.trade_executor import execute_trade_live

async def start_auto_executor(delay=60, min_quality=6, max_budget=100):
    while True:
        try:
            logging.info(f"[AUTO_EXECUTOR] מתחיל סריקה חיה... (min_quality={min_quality})")
            trades = await scan_all(min_quality=min_quality)

            if not trades:
                logging.info("[AUTO_EXECUTOR] לא נמצאו טריידים מתאימים")
                await asyncio.sleep(delay)
                continue

            trade = trades[0]
            logging.info(f"[AUTO_EXECUTOR] מבצע טרייד חי על {trade['symbol']} ({trade['direction']})")

            await asyncio.to_thread(
                execute_trade_live,
                symbol=trade["symbol"],
                entry=trade.get("close", None),
                stop=trade.get("stop", None),
                tp=trade.get("tp", None),
                direction=trade["direction"],
                leverage=10,
                budget_usd=max_budget,
                use_grid=False,
                use_trailing=True
            )

        except Exception as e:
            logging.error(f"[AUTO_EXECUTOR] שגיאה: {e}")

        await asyncio.sleep(delay)







