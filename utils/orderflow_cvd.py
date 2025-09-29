# utils/orderflow_cvd.py (תוספת)
import pandas as pd
def build_delta_per_bar(trades_df: pd.DataFrame, ohlcv_df: pd.DataFrame) -> pd.Series:
    """
    trades_df: ['T'(ms), 'q', 'm'(bool)]   m=True => SELL aggression
    מחזיר Series של Δ לונג-שורט בכל נר (index = ohlcv_df.index)
    """
    if trades_df is None or trades_df.empty:
        return pd.Series(0.0, index=ohlcv_df.index)
    t = trades_df.copy()
    t["ts"] = pd.to_datetime(t["T"], unit="ms", utc=True)
    t["delta"] = t["q"].astype(float) * np.where(t["m"].astype(bool), -1.0, +1.0)
    # קיבוץ לפי סלוט נרות (נניח open_time):
    bins = pd.IntervalIndex.from_arrays(ohlcv_df["open_time"], ohlcv_df["close_time"], closed="left")
    # מיפוי כל טרייד לבין-הזמנים המתאים – אפשר גם merge_asof
    # (בפועל מומלץ merge_asof עם tol)
    t = t.set_index("ts").sort_index()
    ohlcv = ohlcv_df.copy()
    ohlcv["delta"] = 0.0
    for i in range(len(ohlcv)):
        mask = (t.index >= ohlcv["open_time"].iloc[i]) & (t.index < ohlcv["close_time"].iloc[i])
        ohlcv.loc[ohlcv.index[i], "delta"] = t.loc[mask, "delta"].sum()
    return ohlcv["delta"].astype(float)

