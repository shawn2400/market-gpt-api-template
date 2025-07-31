# check_env.py
import os
import importlib
import openai
from binance.client import Client
import requests

print("\U0001F527 AlgoGPT Full Environment Check")

# === 1. בדיקת משתני סביבה
print("\U0001F50D Checking environment variables...")
required_vars = [
    "BINANCE_API_KEY", "BINANCE_API_SECRET", "OPENAI_API_KEY",
    "AUTO_RUN", "MIN_QUALITY_SCORE", "MAX_TRADE_BUDGET", "SCAN_INTERVAL"
]
missing = [var for var in required_vars if not os.getenv(var)]
if missing:
    print(f"\u274C Missing: {', '.join(missing)}")
else:
    print("\u2705 All required environment variables are set.")

# === 2. בדיקת מודולים חיוניים
print("\U0001F4E6 Checking Python modules...")
modules = ["python_dotenv", "python_binance", "scikit_learn"]
missing_modules = []
for mod in modules:
    try:
        importlib.import_module(mod)
    except ImportError:
        missing_modules.append(mod)
if missing_modules:
    print(f"\u274C Missing Python modules: {', '.join(missing_modules)}")
else:
    print("\u2705 All required Python modules installed.")

# === 3. בדיקת Binance API
print("\U0001F510 Checking Binance API connection...")
try:
    client = Client(api_key=os.getenv("BINANCE_API_KEY"), api_secret=os.getenv("BINANCE_API_SECRET"))
    account = client.get_account()
    print("\u2705 Binance API connection successful.")
except Exception as e:
    print(f"\u274C Binance API error: {e}")

# === 4. בדיקת OpenAI API
print("\U0001F916 Checking OpenAI API...")
openai.api_key = os.getenv("OPENAI_API_KEY")
try:
    openai.models.list()
    print("\u2705 OpenAI API key is valid.")
except Exception as e:
    print(f"\u274C OpenAI API error: {e}")

# === 5. בדיקת LunarCrush (אם רלוונטי)
if os.getenv("LUNARCRUSH_API_KEY"):
    print("\U0001F319 Checking LunarCrush API...")
    try:
        r = requests.get("https://api.lunarcrush.com/v2?data=assets&key=" + os.getenv("LUNARCRUSH_API_KEY"), timeout=5)
        if r.status_code == 200:
            print("\u2705 LunarCrush API responded OK.")
        else:
            print(f"\u274C LunarCrush API error: {r.status_code} – {r.text}")
    except Exception as e:
        print(f"\u274C LunarCrush API error: {e}")

# === 6. בדיקת סטטוס שרת
print("\U0001F6A6 Checking local server at http://localhost:5000 ...")
try:
    res = requests.get("http://localhost:5000", timeout=3)
    if res.status_code == 200:
        print("\u2705 Local server is running.")
    else:
        print(f"\u274C Server responded with status: {res.status_code}")
except Exception as e:
    print(f"\u274C Server health check error: {e}")


