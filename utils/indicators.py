# indicators_utils.py – גרסה מלאה מתקדמת

import ta
import pandas as pd


def compute_indicators(df, volume_window=20):
    try:
        # EMA
        df['ema_21'] = ta.trend.EMAIndicator(close=df['close'], window=21).ema_indicator()
        df['ema_50'] = ta.trend.EMAIndicator(close=df['close'], window=50).ema_indicator()

        # RSI
        df['rsi'] = ta.momentum.RSIIndicator(close=df['close'], window=14).rsi()

        # MACD
        macd = ta.trend.MACD(close=df['close'])
        df['macd'] = macd.macd()
        df['macd_signal'] = macd.macd_signal()
        df['macd_hist'] = macd.macd_diff()

        # ADX
        df['adx'] = ta.trend.ADXIndicator(high=df['high'], low=df['low'], close=df['close']).adx()

        # ATR
        df['atr'] = ta.volatility.AverageTrueRange(high=df['high'], low=df['low'], close=df['close']).average_true_range()

        # Stochastic Oscillator
        stoch = ta.momentum.StochasticOscillator(high=df['high'], low=df['low'], close=df['close'])
        df['stoch_k'] = stoch.stoch()
        df['stoch_d'] = stoch.stoch_signal()

        # OBV
        obv = ta.volume.OnBalanceVolumeIndicator(close=df['close'], volume=df['volume'])
        df['obv'] = obv.on_balance_volume()
        df['obv_trend'] = df['obv'].diff() > 0

        # VWAP
        df['vwap'] = (df['close'] * df['volume']).cumsum() / df['volume'].cumsum()
        df['vwap_trend'] = df['close'] > df['vwap']

        # Volume mean
        df['volume_mean'] = df['volume'].rolling(window=volume_window).mean()

        # CCI
        df['cci'] = ta.trend.CCIIndicator(high=df['high'], low=df['low'], close=df['close'], window=20).cci()

        # Bollinger Bands
        bb = ta.volatility.BollingerBands(close=df['close'], window=20)
        df['bb_upper'] = bb.bollinger_hband()
        df['bb_lower'] = bb.bollinger_lband()
        df['bb_width'] = df['bb_upper'] - df['bb_lower']

        # MFI
        mfi = ta.volume.MFIIndicator(high=df['high'], low=df['low'], close=df['close'], volume=df['volume'])
        df['mfi'] = mfi.money_flow_index()

        # Doji
        df['is_doji'] = (abs(df['close'] - df['open']) / (df['high'] - df['low'] + 1e-6)) < 0.1

        # Grid Signal
        df['grid_signal'] = ((df['rsi'] < 35) & (df['macd_hist'] > 0) & (df['adx'] > 17))

        # טכני משוקלל (לא חובה – אבל שימושי להסקת AI)
        df['tech_score'] = (
            (df['rsi'].between(45, 60)) * 1 +
            (df['adx'] > 20) * 1 +
            (df['macd_hist'] > 0) * 1 +
            (df['close'] > df['ema_21']) * 1
        )

        df.dropna(inplace=True)
        return df

    except Exception as e:
        print(f"[!] שגיאה בחישוב אינדיקטורים: {e}")
        return df


# שילוב עם backtest_utils.py
def prepare_indicators_for_backtest(df):
    return compute_indicators(df)

# שילוב עם סריקת שוק חיה (scanner_utils.py)
def prepare_indicators_for_live_scan(df):
    return compute_indicators(df)






