import matplotlib.pyplot as plt
import os
from datetime import datetime

def generate_sample_chart(
    x=None,
    y=None,
    title: str = "📊 גרף מבחן של AlgoGPT",
    xlabel: str = "שלבים",
    ylabel: str = "תוצאה",
    save_dir: str = "static",
    filename: str = None
) -> str:
    """
    יוצר גרף לדוגמה או לפי נתונים נתונים. מחזיר את הנתיב לקובץ שנשמר.
    """
    try:
        # נתונים ברירת מחדל
        if x is None or y is None:
            x = [1, 2, 3, 4, 5]
            y = [5, 6, 7, 6, 5]

        if len(x) != len(y):
            raise ValueError("ה־X וה־Y חייבים להיות באורך זהה")

        os.makedirs(save_dir, exist_ok=True)
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        filename = filename or f"sample_chart_{timestamp}.png"
        save_path = os.path.join(save_dir, filename)

        plt.figure(figsize=(8, 5))
        plt.plot(x, y, marker='o', linestyle='-', color='navy', linewidth=2, label="סדרה")
        plt.title(title, fontsize=16)
        plt.xlabel(xlabel, fontsize=12)
        plt.ylabel(ylabel, fontsize=12)
        plt.grid(True, linestyle='--', alpha=0.5)

        # הוספת הערות לנקודות
        for i, value in enumerate(y):
            plt.text(x[i], y[i] + 0.3, str(value), ha='center', fontsize=9)

        plt.legend()
        plt.tight_layout()
        plt.savefig(save_path)
        plt.close()

        print(f"✅ גרף נשמר בהצלחה: {save_path}")
        return save_path

    except Exception as e:
        print(f"[!] שגיאה ביצירת גרף: {e}")
        return None


# קריאה ישירה לבדיקה
if __name__ == "__main__":
    generate_sample_chart()

