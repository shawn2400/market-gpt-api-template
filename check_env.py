import os
import importlib
import requests
from dotenv import load_dotenv

load_dotenv()

REQUIRED_ENV_VARS = [
    "BINANCE_API_KEY",
    "BINANCE_API_SECRET",
    "OPENAI_API_KEY",
    "LUNARCRUSH_API_KEY",
    "ALERT_EMAIL_ADDRESS",
    "ALERT_EMAIL_PASSWORD",
    "ALERT_TO_EMAIL",
]

REQUIRED_MODULES = [
    "fastapi", "uvicorn", "python_dotenv", "python_binance", "openai",
    "pandas", "numpy", "scipy", "scikit_learn", "ta",
    "matplotlib", "fpdf", "requests", "aiohttp", "ujson"
]

def check_env_vars():
    print("🔍 Checking environment variables...")
    missing = [var for var in REQUIRED_ENV_VARS if not os.getenv(var)]
    if missing:
        print("❌ Missing env vars:", ", ".join(missing))
    else:
        print("✅ All required environment variables are set.")

def check_modules():
    print("📦 Checking Python modules...")
    missing = []
    for module in REQUIRED_MODULES:
        try:
            importlib.import_module(module)
        except ImportError:
            missing.append(module)
    if missing:
        print("❌ Missing Python modules:", ", ".join(missing))
    else:
        print("✅ All required modules are installed.")

def check_binance():
    print("🔐 Checking Binance API connection...")
    try:
        from binance.client import Client
        client = Client(os.getenv("BINANCE_API_KEY"), os.getenv("BINANCE_API_SECRET"))
        account = client.futures_account()
        print(f"✅ Binance connected. Account status: {account.get('canTrade')}")
    except Exception as e:
        print("❌ Binance API error:", str(e))

def check_openai():
    print("🤖 Checking OpenAI API...")
    try:
        import openai
        openai.api_key = os.getenv("OPENAI_API_KEY")
        models = openai.models.list()
        if models.data:
            print("✅ OpenAI connected. Models available:", [m.id for m in models.data[:2]])
        else:
            print("⚠️ OpenAI connected but no models returned.")
    except Exception as e:
        print("❌ OpenAI API error:", str(e))

def check_lunarcrush():
    print("🌙 Checking LunarCrush API...")
    try:
        key = os.getenv("LUNARCRUSH_API_KEY")
        url = f"https://api.lunarcrush.com/v2?data=assets&key={key}"
        resp = requests.get(url)
        if resp.status_code == 200:
            print("✅ LunarCrush API is responsive.")
        else:
            print(f"⚠️ LunarCrush API returned status {resp.status_code}")
    except Exception as e:
        print("❌ LunarCrush API error:", str(e))

def check_server_health():
    print("🚦 Checking server health at / ...")
    try:
        url = os.getenv("SERVER_URL", "http://localhost:5000")
        resp = requests.get(url + "/")
        if resp.status_code == 200:
            print("✅ Server is running:", resp.json())
        else:
            print(f"⚠️ Server returned status {resp.status_code}")
    except Exception as e:
        print("❌ Server health check error:", str(e))

if __name__ == "__main__":
    print("🔧 AlgoGPT Full Environment Check")
    check_env_vars()
    check_modules()
    check_binance()
    check_openai()
    check_lunarcrush()
    check_server_health()

