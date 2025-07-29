# utils/sl_tp_utils.py

def calculate_sl_tp(df, direction):
    """
    מחשב ערכי Stop Loss ו־Take Profit לפי אחוזים מהמחיר האחרון.

    Args:
        df (pd.DataFrame): טבלת נתונים עם עמודת 'close'
        direction (str): "LONG" או "SHORT"

    Returns:
        dict: {"entry": ..., "stop": ..., "tp": ...}
    """
    if df.empty or "close" not in df.columns:
        raise ValueError("ה־DataFrame ריק או חסרה עמודת close")

    entry = float(df["close"].iloc[-1])

    sl_pct = 0.01   # סטופ לוס 1%
    tp_pct = 0.015  # טייק פרופיט 1.5%

    if direction.upper() == "LONG":
        stop = entry * (1 - sl_pct)
        tp = entry * (1 + tp_pct)
    elif direction.upper() == "SHORT":
        stop = entry * (1 + sl_pct)
        tp = entry * (1 - tp_pct)
    else:
        raise ValueError("כיוון לא חוקי: חייב להיות 'LONG' או 'SHORT'")

    return {
        "entry": round(entry, 4),
        "stop": round(stop, 4),
        "tp": round(tp, 4)
    }
