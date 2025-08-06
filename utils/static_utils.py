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


