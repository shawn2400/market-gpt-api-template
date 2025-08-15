# utils/static_utils.py
import os
from datetime import datetime
import matplotlib
matplotlib.use('Agg')  # מצב ללא GUI לשרתים
import matplotlib.pyplot as plt
import pandas as pd
from typing import Optional, List

def create_sample_chart(x: List[float], y: List[float], title: str = "📈 גרף דוגמה", filename: str = "chart.png") -> Optional[str]:
    """
    יוצר ושומר גרף פשוט בתיקיית static, ומחזיר נתיב מלא לקובץ.
    """
    try:
        os.makedirs("static", exist_ok=True)
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        full_path = os.path.join("static", f"{timestamp}_{filename}")

        plt.figure(figsize=(6, 4))
        plt.plot(x, y, marker='o', linestyle='-', label="קו מגמה")
        plt.title(title, fontsize=14)
        plt.xlabel("ציר X", fontsize=12)
        plt.ylabel("ציר Y", fontsize=12)
        plt.grid(True)
        plt.legend()
        plt.tight_layout()
        plt.savefig(full_path, dpi=150)
        plt.close()

        return full_path
    except Exception as e:
        print(f"[static_utils] ❌ שגיאה ביצירת גרף: {e}")
        return None

def detect_pattern(df: pd.DataFrame) -> str:
    """
    מזהה תבנית נר בסיסית מהשורה האחרונה.
    מחזיר: ["Doji", "Hammer", "Shooting Star", ""]
    """
    try:
        if df is None or df.empty:
            return ""
        need = {"open", "high", "low", "close"}
        if not need.issubset(df.columns):
            return ""

        last = df.iloc[-1]
        open_price = float(last["open"])
        close_price = float(last["close"])
        high = float(last["high"])
        low = float(last["low"])

        body = abs(close_price - open_price)
        candle_range = high - low
        if candle_range <= 0:
            return ""

        upper_shadow = high - max(open_price, close_price)
        lower_shadow = min(open_price, close_price) - low

        if body < candle_range * 0.2:
            return "Doji"
        if lower_shadow > body * 2 and body > upper_shadow:
            return "Hammer"
        if upper_shadow > body * 2 and body > lower_shadow:
            return "Shooting Star"
        return ""
    except Exception:
        return ""





