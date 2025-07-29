import ta
import pandas as pd
import numpy as np

def supertrend(df, period=10, multiplier=3):
    # ... (השארת הקוד כפי שהוא)
    # ...

def compute_indicators(df, volume_window=20):
    if df.empty:
        print("[!] DataFrame ריק - אין נתונים לחישוב אינדיקטורים")
        return pd.DataFrame()
    required_cols = ['open', 'high', 'low', 'close', 'volume']
    for col in required_cols:
        if col not in df.columns:
            print(f"[!] חסרה עמודה דרושה: {col}")
            return pd.DataFrame()

    if len(df) < 30:
        print(f"[!] מספר שורות קטן מ-30 ({len(df)}) - לא מספיק נתונים")
        return pd.DataFrame()

    try:
        # חישוב אינדיקטורים (כמו בקוד שלך)
        df['ema_21'] = ta.trend.EMAIndicator(close=df['close'], window=21).ema_indicator()
        # ... שאר החישובים ...

        # בסוף, במקום dropna יש מילוי NaN כדי לא לאבד את כל הנתונים
        df.fillna(method='ffill', inplace=True)
        df.fillna(method='bfill', inplace=True)

        return df

    except Exception as e:
        print(f"[!] שגיאה בחישוב אינדיקטורים: {e}")
        return pd.DataFrame()







