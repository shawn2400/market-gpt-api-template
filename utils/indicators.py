import pandas as pd
import numpy as np

def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    # מחיקת NaN/שכפולים
    df.dropna(inplace=True)
    df = df[~df.index.duplicated(keep='last')]

    # EMA
    df["ema_21"] = df["close"].ewm(span=21, adjust=False).mean()
    df["ema_50"] = df["close"].ewm(span=50, adjust=False).mean()

    # ATR
    df["H-L"] = df["high"] - df["low"]
    df["H-C"] = np.abs(df["high"] - df["close"].shift())
    df["L-C"] = np.abs(df["low"] - df["close"].shift())
    df["TR"] = df[["H-L", "H-C", "L-C"]].max(axis=1)
    df["ATR"] = df["TR"].rolling(window=14).mean()

    # RSI
    delta = df["close"].diff()
    gain = np.where(delta > 0, delta, 0)
    loss = np.where(delta < 0, -delta, 0)
    avg_gain = pd.Series(gain).rolling(window=14).mean()
    avg_loss = pd.Series(loss).rolling(window=14).mean()
    rs = avg_gain / avg_loss
    df["RSI"] = 100 - (100 / (1 + rs))

    # MACD
    exp1 = df["close"].ewm(span=12, adjust=False).mean()
    exp2 = df["close"].ewm(span=26, adjust=False).mean()
    df["MACD"] = exp1 - exp2
    df["MACD_signal"] = df["MACD"].ewm(span=9, adjust=False).mean()
    df["MACD_hist"] = df["MACD"] - df["MACD_signal"]

    # ADX
    df["+DM"] = np.where((df["high"] - df["high"].shift()) > (df["low"].shift() - df["low"]),
                         df["high"] - df["high"].shift(), 0)
    df["-DM"] = np.where((df["low"].shift() - df["low"]) > (df["high"] - df["high"].shift()),
                         df["low"].shift() - df["low"], 0)
    tr14 = df["TR"].rolling(window=14).sum()
    plus_dm14 = df["+DM"].rolling(window=14).sum()
    minus_dm14 = df["-DM"].rolling(window=14).sum()
    plus_di14 = 100 * (plus_dm14 / tr14)
    minus_di14 = 100 * (minus_dm14 / tr14)
    dx = 100 * np.abs(plus_di14 - minus_di14) / (plus_di14 + minus_di14)
    df["ADX"] = dx.rolling(window=14).mean()

    # VWAP (לגרף תוך יומי)
    df["vwap"] = (df["close"] * df["volume"]).cumsum() / df["volume"].cumsum()

    # סטיית תקן
    df["stddev_20"] = df["close"].rolling(window=20).std()

    # Supertrend (10,3)
    period = 10
    multiplier = 3
    hl2 = (df["high"] + df["low"]) / 2
    atr = df["ATR"]
    upperband = hl2 + (multiplier * atr)
    lowerband = hl2 - (multiplier * atr)
    supertrend = [True] * len(df)

    for i in range(1, len(df)):
        if df["close"].iloc[i] > upperband.iloc[i - 1]:
            supertrend[i] = True
        elif df["close"].iloc[i] < lowerband.iloc[i - 1]:
            supertrend[i] = False
        else:
            supertrend[i] = supertrend[i - 1]
            if supertrend[i] and lowerband.iloc[i] < lowerband.iloc[i - 1]:
                lowerband.iloc[i] = lowerband.iloc[i - 1]
            if not supertrend[i] and upperband.iloc[i] > upperband.iloc[i - 1]:
                upperband.iloc[i] = upperband.iloc[i - 1]

    df["supertrend"] = supertrend
    df["supertrend_upper"] = upperband
    df["supertrend_lower"] = lowerband

    # מחיקת עמודות עזר
    drop_cols = ["H-L", "H-C", "L-C", "+DM", "-DM", "TR"]
    df.drop(columns=[col for col in drop_cols if col in df.columns], inplace=True, errors="ignore")

    return df






















