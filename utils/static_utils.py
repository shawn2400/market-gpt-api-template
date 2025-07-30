# utils/static_utils.py

import matplotlib.pyplot as plt
import os
from datetime import datetime

def create_sample_chart(x: list, y: list, title: str = "📈 גרף דוגמה", filename: str = "chart.png") -> str | None:
    """
    יוצר ושומר גרף פשוט בתיקייה static.
    מחזיר את הנתיב המלא של הקובץ או None אם נכשל.
    """
    try:
        output_dir = "static"
        os.makedirs(output_dir, exist_ok=True)
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        full_path = os.path.join(output_dir, f"{timestamp}_{filename}")

        plt.figure(figsize=(6, 4))
        plt.plot(x, y, marker='o', linestyle='-', label="קו מגמה")
        plt.title(title)
        plt.xlabel("ציר X")
        plt.ylabel("ציר Y")
        plt.grid(True)
        plt.legend()
        plt.tight_layout()
        plt.savefig(full_path)
        plt.close()

        return full_path
    except Exception as e:
        print(f"[static_utils] שגיאה ביצירת הגרף: {e}")
        return None
