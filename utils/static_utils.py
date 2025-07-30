# utils/static_utils.py
import matplotlib.pyplot as plt
import os
from datetime import datetime

def create_sample_chart(x: list, y: list, title: str = "📈 גרף דוגמה", filename: str = "chart.png") -> str:
    """
    יוצר ושומר גרף פשוט מהנתונים שסופקו בתיקייה static.
    מחזיר את הנתיב המלא של הקובץ.
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
        plt.savefig(full_path)
        plt.close()

        print(f"✅ גרף נשמר: {full_path}")
        return full_path
    except Exception as e:
        print(f"[!] שגיאה ביצירת הגרף: {e}")
        return None
