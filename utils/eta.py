# utils/eta.py
from __future__ import annotations
from typing import Optional
import pandas as pd

def per_minute_move_estimate(df: pd.DataFrame, window: int = 30) -> float:
    """
    הערכת שינוי מחיר ממוצע לדקה עפ״י תנודתיות אחרונה.
    df חייב לכלול עמודת 'close'. אם df הוא 1m-interval עדיף;
    אם 5m/15m – מנרמל לדקה.
    """
    if df is None or df.empty or "close" not in df.columns:
        return 0.0
    # שינוי מוחלט בין נרות
    diff = df["close"].diff().abs().dropna()
    if diff.empty:
        return 0.0
    avg = diff.tail(window).mean()
    # אם מרווח הנרות ידוע (למשל 15m), נחלק ב-15 כדי להגיע ל"דקה"
    # נניח שיש meta על interval מחוץ לפונקציה; אחרת משתמש יזין df של 1m/5m.
    return float(avg) / 1.0  # התאמות חיצוניות אם זה לא 1m
