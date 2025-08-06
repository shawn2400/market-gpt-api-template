# utils/static_utils.py

import os
from datetime import datetime
import matplotlib
matplotlib.use('Agg')  # שימוש במצב ללא GUI לצורך הפקה על שרת
import matplotlib.pyplot as plt


def create_sample_chart(x: list, y: list, title: str = "📈 גרף דוגמה", filename: str = "chart.png") -> str:
    """
    יוצר ושומר גרף פשוט מהנתונים שסופקו בתיקייה static.
    מחזיר את הנתיב המלא של הקובץ או None אם יש שגיאה.
    """
    try:
        # ודא שהתיקייה קיימת
        os.makedirs("static", exist_ok=True)

        # צור שם ייחודי לפי תאריך
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        full_path = os.path.join("static", f"{timestamp}_{filename}")

        # ציור הגרף
        plt.figure(figsize=(6, 4))
        plt.plot(x, y, marker='o', linestyle='-', label="קו מגמה")
        plt.title(title, fontsize=14)
        plt.xlabel("ציר X", fontsize=12)
        plt.ylabel("ציר Y", fontsize=12)
        plt.grid(True)
        plt.legend()
        plt.tight_layout()

        # שמירה
        plt.savefig(full_path, dpi=150)
        plt.close()

        print(f"✅ גרף נשמר בהצלחה: {full_path}")
        return full_path

    except Exception as e:
        print(f"[static_utils] ❌ שגיאה ביצירת גרף: {e}")
        return None


def detect_pattern(candle: dict) -> str:
    """
    מזהה תבנית נר בסיסית מתוך נתוני OHLC.
    מחזיר אחד מ־["Doji", "Hammer", "Shooting Star", ""].
    """
    try:
        open_price = candle.get("open", 0)
        close_price = candle.get("close", 0)
        high = candle.get("high", 0)
        low = candle.get("low", 0)

        body = abs(close_price - open_price)
        candle_range = high - low
        if candle_range == 0:
            return ""

        upper_shadow = high - max(open_price, close_price)
        lower_shadow = min(open_price, close_price) - low

        if body < candle_range * 0.2:
            return "Doji"
        elif lower_shadow > body * 2 and body > upper_shadow:
            return "Hammer"
        elif upper_shadow > body * 2 and body > lower_shadow:
            return "Shooting Star"
        else:
            return ""
    except Exception:
        return ""



