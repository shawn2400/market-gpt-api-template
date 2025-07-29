import matplotlib.pyplot as plt
import os

def generate_sample_chart(save_path="static/chart.png"):
    """
    יוצר גרף לדוגמה ושומר אותו כ־PNG.
    """
    # יצירת תיקייה אם אינה קיימת
    os.makedirs(os.path.dirname(save_path), exist_ok=True)

    # נתונים לדוגמה
    x = [1, 2, 3, 4, 5]
    y = [5, 6, 7, 6, 5]

    # יצירת גרף
    plt.figure(figsize=(8, 5))
    plt.plot(x, y, marker='o', linestyle='-', color='navy', linewidth=2)
    plt.title("📊 גרף מבחן של AlgoGPT", fontsize=16)
    plt.xlabel("שלבים", fontsize=12)
    plt.ylabel("תוצאה", fontsize=12)
    plt.grid(True, linestyle='--', alpha=0.5)

    # הוספת הערות לגרף
    for i, value in enumerate(y):
        plt.text(x[i], y[i] + 0.2, str(value), ha='center', fontsize=10)

    # שמירה
    plt.tight_layout()
    plt.savefig(save_path)
    plt.close()
    print(f"✅ גרף לדוגמה נשמר בהצלחה: {save_path}")

# קריאה ישירה אם קובץ מופעל עצמאית
if __name__ == "__main__":
    generate_sample_chart()

