import ta
import pandas as pd
import numpy as np

# === פונקציית סופרטרנד מלאה ===
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

# === פונקציית אינדיקטורים מלאה ===
def compute_indicators(df, volume_window=20):
    # בדיקה בסיסית לפני חישוב אינדיקטורים
    if df.empty or any(col not in df.columns for col in ['open','high','low','close','volume']):
        print("[!] df לא תקין לחישוב אינדיקטורים - חסרים עמודות חיוניות או ריק")
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

        print(f"[indicators] לפני dropna: {len(df)} שורות")
        df.dropna(inplace=True)
        print(f"[indicators] אחרי dropna: {len(df)} שורות")

        if len(df) < 30:
            print("[!] אזהרה: אחרי dropna, מעט מדי נתונים לניתוח אמין")

        return df

    except Exception as e:
        print(f"[!] שגיאה בחישוב אינדיקטורים: {e}")
        return df

# ==== שימוש לקוד חיצוני (ל־Backtest, ל־LIVE וכו׳) ====
def prepare_indicators_for_backtest(df):
    return compute_indicators(df)

def prepare_indicators_for_live_scan(df):
    return compute_indicators(df)








