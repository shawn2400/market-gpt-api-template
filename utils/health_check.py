# utils/health_check.py

import os
import logging
from utils.binance_client import client
from dotenv import load_dotenv

REQUIRED_ENV = [
    "BINANCE_API_KEY",
    "BINANCE_API_SECRET",
    "OPENAI_API_KEY",
    "CRYPTO_PANIC_API_KEY",
    "ALERT_EMAIL_ADDRESS",
    "ALERT_EMAIL_PASSWORD",
]

CRITICAL_FILES = [
    "watchlist.json",
    "open_trades.json",
    "pnl_tracker.json",
]

def check_env():
    print("🔎 בדיקת משתני סביבה:")
    failed = False
    for k in REQUIRED_ENV:
        v = os.getenv(k)
        if not v:
            print(f"❌ חסר: {k}")
            failed = True
        else:
            print(f"✅ {k} ... OK")
    return not failed

def check_binance():
    print("\n🔎 בדיקת Binance client:")
    try:
        ping = client.ping()
        print(f"✅ ping: {ping}")
        account = client.futures_account()
        print(f"✅ Futures account: OK")
        return True
    except Exception as e:
        print(f"❌ Binance client לא זמין: {e}")
        return False

def check_files():
    print("\n🔎 בדיקת קבצים קריטיים:")
    all_ok = True
    for fname in CRITICAL_FILES:
        if os.path.exists(fname):
            print(f"✅ נמצא: {fname}")
        else:
            print(f"❌ חסר: {fname}")
            all_ok = False
    return all_ok

def main():
    print("=== Health Check ===")
    env_ok = check_env()
    binance_ok = check_binance()
    files_ok = check_files()
    if env_ok and binance_ok and files_ok:
        print("✅ המערכת מוכנה להרצה!")
    else:
        print("❌ יש בעיות – בדוק את ההודעות למעלה.")

if __name__ == "__main__":
    main()
