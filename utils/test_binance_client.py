# tests/test_binance_client.py

from utils.binance_client import client, init_binance_client

def test_binance_connectivity():
    print("🔄 בודק חיבור ל־Binance...")

    if not client:
        print("❌ client לא מאותחל. מנסה לאתחל...")
        init_binance_client()

    if client:
        try:
            # בדיקת ping
            ping = client.ping()
            assert ping == {}, "Ping נכשל"

            # בדיקת חשבון פיוצ'רס
            futures_info = client.futures_account()
            assert "assets" in futures_info, "גישה לפיוצ'רס נכשלה"

            print("✅ חיבור תקין ל־Binance (Futures + Spot)")
        except Exception as e:
            print(f"❌ שגיאה: {e}")
    else:
        print("❌ client עדיין None – בדוק מפתחות API או קובץ .env")

if __name__ == "__main__":
    test_binance_connectivity()
