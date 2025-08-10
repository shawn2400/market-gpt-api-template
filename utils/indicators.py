# utils/indicators.py
# חישובי אינדיקטורים יציבים על DataFrame עם עמודות: open, high, low, close, volume (Index=Datetime[UTC])
import numpy as np
import pandas as pd
import logging

from ta.momentum import RSIIndicator
from ta.trend import ADXIndicator, MACD, EMAIndicator
from ta.volatility import AverageTrueRange

# פרמטרים דיפולטיים (אפשר לשנות בהמשך אם תרצה)
_RSI = 14
_ADX = 14
_ATR = 14
_EMA_FAST = 21
_EMA_SLOW = 50
_MACD_FAST = 12
_MACD_SLOW = 26
_MACD_SIGNAL = 9
_ST_PERIOD = 10
_ST_MULT = 3.0

def _ensure_df(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    need = {"open", "high", "low", "close", "volume"}
    if not need.issubset(df.columns):
        missing = need - set(df.columns)
        logging.warning(f"[indicators] חסרות עמודות לבסיס: {missing}")
        return pd.DataFrame()
    out = df.copy()
    # טיפוסי float
    for c in ("open", "high", "low", "close", "volume"):
        out[c] = pd.to_numeric(out[c], errors="coerce")
    # אינדקס זמן מסודר
    if not isinstance(out.index, pd.DatetimeIndex):
        if "timestamp" in out.columns:
            out["timestamp"] = pd.to_datetime(out["timestamp"], utc=True, errors="coerce")
            out.set_index("timestamp", inplace=True)
        else:
            out.index = pd.to_datetime(out.index, utc=True, errors="coerce")
    out.sort_index(inplace=True)
    # ניקוי ראשוני
    out.replace([np.inf, -np.inf], np.nan, inplace=True)
    out.dropna(subset=["open", "high", "low", "close", "volume"], inplace=True)
    return out

def _vwap(df: pd.DataFrame) -> pd.Series:
    tp = (df["high"] + df["low"] + df["close"]) / 3.0
    vol = df["volume"].astype(float)
    # VWAP מוגדר רק כשיש נפח מצטבר חיובי
    cum_vol = vol.replace(0, np.nan).fillna(0).cumsum()
    cum_pv = (tp * vol).fillna(0).cumsum()
    vwap = cum_pv / cum_vol.replace(0, np.nan)
    return vwap

def _supertrend(df: pd.DataFrame, period: int = _ST_PERIOD, multiplier: float = _ST_MULT) -> pd.Series:
    """
    מימוש Supertrend קלאסי:
    - UB/LB בסיסיים מה-ATR
    - FUB/FLB (פסים סופיים) מתעדכנים יחסית לערך הקודם ולסגירה קודמת
    - ST נבחר לפי חציה של המחיר את הפס הנוכחי
    """
    # חשוב: ממלאים ערכים התחלתיים כדי למנוע NaN בתחילת הסדרה
    atr = AverageTrueRange(
        high=df["high"], low=df["low"], close=df["close"],
        window=period, fillna=True
    ).average_true_range()

    hl2 = (df["high"] + df["low"]) / 2.0
    upper_basic = hl2 + multiplier * atr
    lower_basic = hl2 - multiplier * atr

    fub = upper_basic.copy()
    flb = lower_basic.copy()

    for i in range(1, len(df)):
        # Final Upper Band
        if (upper_basic.iloc[i] < fub.iloc[i-1]) or (df["close"].iloc[i-1] > fub.iloc[i-1]):
            fub.iloc[i] = upper_basic.iloc[i]
        else:
            fub.iloc[i] = fub.iloc[i-1]

        # Final Lower Band
        if (lower_basic.iloc[i] > flb.iloc[i-1]) or (df["close"].iloc[i-1] < flb.iloc[i-1]):
            flb.iloc[i] = lower_basic.iloc[i]
        else:
            flb.iloc[i] = flb.iloc[i-1]

    st = pd.Series(index=df.index, dtype=float)
    trend = pd.Series(index=df.index, dtype=int)

    # אתחול מגמה ראשונית
    trend.iloc[0] = 1 if df["close"].iloc[0] >= flb.iloc[0] else -1
    st.iloc[0] = flb.iloc[0] if trend.iloc[0] == 1 else fub.iloc[0]

    for i in range(1, len(df)):
        if trend.iloc[i-1] == 1:
            # במגמת UP: מעבר ל-DOWN כשסגירה נופלת מתחת FUB
            if df["close"].iloc[i] <= fub.iloc[i]:
                trend.iloc[i] = -1
                st.iloc[i] = fub.iloc[i]
            else:
                trend.iloc[i] = 1
                st.iloc[i] = flb.iloc[i]
        else:
            # במגמת DOWN: מעבר ל-UP כשסגירה עוברת מעל FLB
            if df["close"].iloc[i] >= flb.iloc[i]:
                trend.iloc[i] = 1
                st.iloc[i] = flb.iloc[i]
            else:
                trend.iloc[i] = -1
                st.iloc[i] = fub.iloc[i]

    return st

def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    מחזיר DF עם כל האינדיקטורים הנדרשים:
      rsi, adx, atr, macd/macd_signal/macd_hist, ema_21, ema_50, vwap, supertrend_dir, pattern (אופציונלי)
    לעולם לא מחזיר ריק אם יש די נתונים בסיסיים (100+ נרות) והסדרה תקינה.
    """
    base = _ensure_df(df)
    if base.empty:
        return pd.DataFrame()

    # נוודא שיש מספיק היסטוריה לאינדיקטורים "ארוכים" ביותר (EMA 50 / MACD 26 / ATR 14)
    if len(base) < 100:
        logging.warning(f"[indicators] מעט מדי נרות ({len(base)}). דרוש לפחות 100.")
        return pd.DataFrame()

    out = base.copy()

    try:
        # EMA
        out["ema_21"] = EMAIndicator(close=out["close"], window=_EMA_FAST, fillna=True).ema_indicator()
        out["ema_50"] = EMAIndicator(close=out["close"], window=_EMA_SLOW, fillna=True).ema_indicator()

        # RSI
        out["rsi"] = RSIIndicator(close=out["close"], window=_RSI, fillna=True).rsi()

        # ADX
        adx_ind = ADXIndicator(high=out["high"], low=out["low"], close=out["close"], window=_ADX, fillna=True)
        out["adx"] = adx_ind.adx()

        # ATR
        out["atr"] = AverageTrueRange(
            high=out["high"], low=out["low"], close=out["close"], window=_ATR, fillna=True
        ).average_true_range()

        # MACD
        macd = MACD(close=out["close"], window_fast=_MACD_FAST, window_slow=_MACD_SLOW, window_sign=_MACD_SIGNAL, fillna=True)
        out["macd"] = macd.macd()
        out["macd_signal"] = macd.macd_signal()
        out["macd_hist"] = macd.macd_diff()

        # VWAP
        out["vwap"] = _vwap(out)

        # Supertrend + כיוון
        st_line = _supertrend(out, period=_ST_PERIOD, multiplier=_ST_MULT)
        out["supertrend"] = st_line
        out["supertrend_dir"] = np.where(out["close"] >= st_line, 1, -1)

        # ניקוי אחרון: להסיר שורות מוקדמות בלי ערכי אינדיקטורים
        cols_needed = ["rsi","adx","atr","macd","macd_signal","macd_hist","ema_21","ema_50","vwap","supertrend","supertrend_dir"]
        out.replace([np.inf, -np.inf], np.nan, inplace=True)
        out.dropna(subset=cols_needed, inplace=True)

        # בטיחות: אם עדיין קצר מאוד, ננסה למלא קדימה/אחורה באופן שמרני
        if len(out) < 20:
            out[cols_needed] = out[cols_needed].ffill().bfill()
            out.dropna(subset=cols_needed, inplace=True)

        if out.empty:
            logging.warning("[indicators] לאחר חישוב וניקוי – הכל נפל ל-NaN. מחזיר ריק.")
            return pd.DataFrame()

        # pattern אופציונלי (כרגע unknown)
        out["pattern"] = "unknown"

        return out

    except Exception as e:
        logging.error(f"[indicators] שגיאה בחישוב אינדיקטורים: {e}", exc_info=True)
        return pd.DataFrame()

















