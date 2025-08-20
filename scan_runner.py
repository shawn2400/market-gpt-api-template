# scan_runner.py
import requests, time

BASE_URL = "https://algogpt-docker.onrender.com"

def find_best_trades(top=25):
    params = {"top": top, "interval": "15m"}
    try:
        resp = requests.get(f"{BASE_URL}/scan", params=params, timeout=90,
                            headers={"Authorization": f"Bearer rnd_I7f7QQ6JXu55tuqfORcQKBdlxMPK"})
        data = resp.json()
    except Exception as e:
        print(f"[שגיאת רשת] {e}")
        return []

    if data.get("count", 0) > 0:
        print(f"✅ נמצאו {data['count']} טריידים")
        return data["items"]
    print("❌ אין טריידים איכותיים כרגע.")
    return []

if __name__ == "__main__":
    print("🔄 AlgoGPT Scan Runner – סריקה חיה")
    while True:
        find_best_trades(top=25)
        time.sleep(60)

