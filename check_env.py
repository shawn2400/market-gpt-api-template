# check_env.py
import os
from dotenv import load_dotenv
import openai
from binance.client import Client

load_dotenv()

def check_env_vars():
    print("\n🔍 בדיקת מפתחות וקונפיגורציה:")
    keys = [
        "BINANCE_API_KEY",
        "BINANCE_API_SECRET",
        "CRYPTO_PANIC_API_KEY",
        "OPENAI_API_KEY",
        "ALERT_EMAIL_ADDRESS",
        "ALERT_EMAIL_PASSWORD",
        "ALERT_TO_EMAIL"
    ]
    for key in keys:
        val = os.getenv(key)
        status = "✅ קיים" if val else "❌ חסר"
        print(f"{key}: {status}")

def check_binance_connection():
    print("\n🔌 בדיקת חיבור ל־Binance:")
    try:
        client = Client(
            api_key=os.getenv("BINANCE_API_KEY"),
            api_secret=os.getenv("BINANCE_API_SECRET")
        )
        acc = client.get_account()
        print(f"✅ חיבור הצליח. {len(acc.get('balances', []))} מטבעות בחשבון.")
    except Exception as e:
        print(f"❌ שגיאה בחיבור ל־Binance: {e}")

def check_openai_connection():
    print("\n🧠 בדיקת חיבור ל־OpenAI:")
    try:
        openai.api_key = os.getenv("OPENAI_API_KEY")
        res = openai.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": "שלום, האם אתה פעיל?"}],
            max_tokens=10
        )
        print("✅ חיבור ל־OpenAI הצליח.")
    except Exception as e:
        print(f"❌ שגיאה בחיבור ל־OpenAI: {e}")

if __name__ == "__main__":
    print("=== 🔧 בדיקת מערכת AlgoGPT ===")
    check_env_vars()
    check_binance_connection()
    check_openai_connection()
    print("\n📋 הבדיקה הסתיימה.\n")
