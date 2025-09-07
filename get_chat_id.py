# get_chat_id.py
import os, requests
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
if not TOKEN:
    raise SystemExit("❌ TELEGRAM_BOT_TOKEN חסר ב-.env")

url = f"https://api.telegram.org/bot{TOKEN}/getUpdates"

try:
    resp = requests.get(url, timeout=10)
    data = resp.json()
except Exception as e:
    raise SystemExit(f"❌ שגיאת רשת: {e}")

if "result" not in data or not data["result"]:
    raise SystemExit("⚠️ אין עדכונים — שלח הודעה לבוט כדי לייצר CHAT_ID")

chat_id = data["result"][-1]["message"]["chat"]["id"]
print("✅ CHAT_ID שלך הוא:", chat_id)

