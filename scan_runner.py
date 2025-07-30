# scan_runner.py
import requests
import time

BASE_URL = "https://algogpt-docker.onrender.com"
frames_quality = [
    ("1h,4h,1d", 7),
    ("15m,1h", 6),
    ("5m,15m", 5),
    ("5m", 5)
]

def filter_by_ai(trades):
    # סינון נוסף: רק טריידים שבהם ה-AI ממליץ בפועל
    filtered = []
    for t in trades:
        ai_op = t.get("ai_opinion", "").lower()
        # נחשב רק אם ה-AI מזהה את הכיוון (לונג/שורט) ולא "error"
        if t["main_direction"].lower() in ai_op and "error" not in ai_op:
            filtered.append(t)
    return filtered

def find_best_trades(top=25):
    for frames, min_quality in frames_quality:
        params = {"frames": frames, "min_quality": min_quality, "top": top}
        try:
            resp = requests.get(f"{BASE_URL}/scan/multi", params=params, timeout=90)
            data = resp.json()
        except Exception as e:
            print(f"[שגיאת רשת] {e}")
            continue

        if data.get("count", 0) > 0:
            print(f"\n✅ נמצאו {data['count']} טריידים (frames={frames}, quality={min_quality})")
            # שלב ניתוח נוסף – להוציא רק מה שה-AI ממליץ:
            trades = filter_by_ai(data["results"])
            print(f"מתוכם, {len(trades)} עם המלצת AI חכמה.")
            for i, trade in enumerate(trades, 1):
                print(f"\n--- טרייד #{i} ---")
                print(f"סימבול: {trade['symbol']}")
                print(f"טרנד: {trade['main_direction']}")
                print(f"איכות: {trade['avg_quality']}")
                print(f"frames: {trade['frames']}")
                print(f"AI: {trade['ai_opinion']}")
            if trades:
                return trades
            # אם לא נשארו אחרי AI – תחפש בקבוצת frames הבאה
    print("❌ אין טריידים איכותיים כרגע.")
    return []

if __name__ == "__main__":
    print("🔄 AlgoGPT Scan Runner – לולאה רצה, הרבה טריידים איכותיים (top=25)")
    while True:
        find_best_trades(top=25)
        print("[⏳] ממתין דקה לסריקה הבאה...\n")
        time.sleep(60)   # לשנות כאן את זמן הסריקה החוזרת אם תרצה
