# utils/indicators.py

import ta
import pandas as pd
import numpy as np
import logging

logging.basicConfig(level=logging.INFO, format='[%(levelname)s] %(message)s')

def supertrend(df, period=10, multiplier=3):
    if df.empty or any(col not in df.columns for col in ['high', 'low', 'close']):
        logging.warning("supertrend: DataFrame חסר עמודות או ריק")
        return df

    hl2 = (df['high'] + df['low']) / 2
    atr = ta.volatility.AverageTrueRange(
        high=df['high'], low=df['low'], close=df['close'], window=period
    ).average_true_range()

    upperband = hl2 + (multiplier * atr)
    lowerband = hl2 - (multiplier * atr)

    final_upperband = upperband.copy()
    final_lowerband = lowerband.copy()
    supertrend_vals = [np.nan] * len(df)
    direction = [1] * len(df)

    for i in range(1, len(df)):
        if df['close'].iloc[i] > final_upperband.iloc[i - 1]:
            direction[i] = 1
        elif df['close'].iloc[i] < final_lowerband.iloc[i - 1]:
            direction[i] = -1
        else:
            direction[i] = direction[i - 1]
            if direction[i] == 1 and final_lowerband.iloc[i] < final_lowerband.iloc[i - 1]:
                final_lowerband.iloc[i] = final_lowerband.iloc[i - 1]
            if direction[i] == -1 and final_upperband.iloc[i] > final_upperband.iloc[i - 1]:
                final_upperband.iloc[i] = final_upperband.iloc[i - 1]

        supertrend_vals[i] = final_lowerband.iloc[i] if direction[i] == 1 else final_upperband.iloc[i]

    df['supertrend'] = supertrend_vals
    df['supertrend_dir'] = direction
    return df

def compute_indicators(df, volume_window=20):
    required_cols = ['open', 'high', 'low', 'close', 'volume']
    if df.empty or any(col not in df.columns for col in required_cols):
        logging.warning(f"compute_indicators: קלט לא תקין (חסרים: {set(required_cols) - set(df.columns)})")
        return df

    try:
        df[required_cols] = df[required_cols].apply(pd.to_numeric, errors='coerce')
        df.dropna(subset=required_cols, inplace=True)

        if len(df) < 50:
            logging.warning("⚠️ פחות מדי נרות לחישוב אינדיקטורים (מתחת ל־50)")
            return df

        # === Trend & Momentum Indicators ===
        df['ema_21'] = ta.trend.EMAIndicator(df['close'], window=21).ema_indicator()
        df['ema_50'] = ta.trend.EMAIndicator(df['close'], window=50).ema_indicator()
        df['ema_100'] = ta.trend.EMAIndicator(df['close'], window=100).ema_indicator()
        df['ema_200'] = ta.trend.EMAIndicator(df['close'], window=200).ema_indicator()

        df['sma_50'] = ta.trend.SMAIndicator(df['close'], window=50).sma_indicator()
        df['sma_200'] = ta.trend.SMAIndicator(df['close'], window=200).sma_indicator()

        df['rsi'] = ta.momentum.RSIIndicator(df['close']).rsi()
        df['stoch_rsi'] = ta.momentum.StochRSIIndicator(df['close']).stochrsi()
        df['williams_r'] = ta.momentum.WilliamsRIndicator(df['high'], df['low'], df['close']).williams_r()

        macd = ta.trend.MACD(df['close'])
        df['macd'] = macd.macd()
        df['macd_signal'] = macd.macd_signal()
        df['macd_hist'] = macd.macd_diff()

        df['adx'] = ta.trend.ADXIndicator(df['high'], df['low'], df['close']).adx()
        df['atr'] = ta.volatility.AverageTrueRange(df['high'], df['low'], df['close']).average_true_range()

        # === Oscillators ===
        stoch = ta.momentum.StochasticOscillator(df['high'], df['low'], df['close'])
        df['stoch_k'] = stoch.stoch()
        df['stoch_d'] = stoch.stoch_signal()

        df['cci'] = ta.trend.CCIIndicator(df['high'], df['low'], df['close']).cci()

        # === Volume + VWAP ===
        df['vwap'] = (df['close'] * df['volume']).cumsum() / df['volume'].cumsum()
        df['vwap_trend'] = df['close'] > df['vwap']
        df['volume_mean'] = df['volume'].rolling(volume_window).mean()
        df['volume_spike'] = df['volume'] > (df['volume_mean'] * 2)

        obv = ta.volume.OnBalanceVolumeIndicator(df['close'], df['volume'])
        df['obv'] = obv.on_balance_volume()
        df['obv_trend'] = df['obv'].diff() > 0

        mfi = ta.volume.MFIIndicator(df['high'], df['low'], df['close'], df['volume'])
        df['mfi'] = mfi.money_flow_index()

        # === Bollinger Bands ===
        bb = ta.volatility.BollingerBands(df['close'])
        df['bb_upper'] = bb.bollinger_hband()
        df['bb_lower'] = bb.bollinger_lband()
        df['bb_width'] = df['bb_upper'] - df['bb_lower']

        # === Candles & Patterns ===
        df['is_doji'] = (abs(df['close'] - df['open']) / (df['high'] - df['low'] + 1e-6)) < 0.1
        df['bullish_engulfing'] = (df['close'] > df['open']) & (df['open'].shift(1) > df['close'].shift(1)) & (df['close'] > df['open'].shift(1))
        df['bearish_engulfing'] = (df['close'] < df['open']) & (df['open'].shift(1) < df['close'].shift(1)) & (df['close'] < df['open'].shift(1))

        # === Signals & Scores ===
        df['ema_cross_bull'] = (df['ema_21'] > df['ema_50']) & (df['ema_21'].shift(1) <= df['ema_50'].shift(1))
        df['ema_cross_bear'] = (df['ema_21'] < df['ema_50']) & (df['ema_21'].shift(1) >= df['ema_50'].shift(1))
        df['macd_cross_bull'] = (df['macd'] > df['macd_signal']) & (df['macd'].shift(1) <= df['macd_signal'].shift(1))
        df['macd_cross_bear'] = (df['macd'] < df['macd_signal']) & (df['macd'].shift(1) >= df['macd_signal'].shift(1))

        df['grid_signal'] = ((df['rsi'] < 35) & (df['macd_hist'] > 0) & (df['adx'] > 17))
        df['tech_score'] = (
            (df['rsi'].between(45, 60)).astype(int) +
            (df['adx'] > 20).astype(int) +
            (df['macd_hist'] > 0).astype(int) +
            (df['close'] > df['ema_21']).astype(int)
        )

        df = supertrend(df)
        df['trend_strength'] = df[['tech_score', 'supertrend_dir']].sum(axis=1)
        df['signal_score'] = df[['ema_cross_bull', 'macd_cross_bull', 'bullish_engulfing']].sum(axis=1)

        df.fillna(method="ffill", inplace=True)
        df.fillna(method="bfill", inplace=True)

        return df

    except Exception as e:
        logging.error(f"[compute_indicators] ❌ שגיאה: {e}")
        return df














