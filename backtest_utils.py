# backtest_utils.py

import pandas as pd
from ta.trend import EMAIndicator, MACD, ADXIndicator
from ta.momentum import RSIIndicator
from ta.volatility import BollingerBands

def backtest_strategy(df):
    df['ema_21'] = EMAIndicator(df['close'], window=21).ema_indicator()
    df['ema_50'] = EMAIndicator(df['close'], window=50).ema_indicator()
    df['macd'] = MACD(df['close']).macd_diff()
    df['rsi'] = RSIIndicator(df['close']).rsi()
    df['adx'] = ADXIndicator(df['high'], df['low'], df['close']).adx()
    df['bb_bbm'] = BollingerBands(df['close']).bollinger_mavg()

    df['signal'] = None
    for i in range(1, len(df)):
        if (
            df['rsi'].iloc[i] < 30 and
            df['macd'].iloc[i] > 0 and
            df['close'].iloc[i] > df['ema_21'].iloc[i] and
            df['adx'].iloc[i] > 20
        ):
            df.at[i, 'signal'] = 'LONG'
        elif (
            df['rsi'].iloc[i] > 70 and
            df['macd'].iloc[i] < 0 and
            df['close'].iloc[i] < df['ema_21'].iloc[i] and
            df['adx'].iloc[i] > 20
        ):
            df.at[i, 'signal'] = 'SHORT'
    return df[['timestamp', 'close', 'signal']]

