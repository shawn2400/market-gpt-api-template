# scan_runner.py
import requests, time, logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
BASE_URL = "https://algogpt-docker.onrender.com"

def find_best_trades(top=25):
    params = {"top": top, "interval": "15m"}
    try:
        resp = requests.get(f"{BASE_URL}/scan", params=params, timeout=90,
                            headers={"Authorization": "Bearer rnd_I7f7QQ6JXu55tuqfORcQKBdlxMPK"})
        data = resp.json()
    except Exception as e:
        logging.error(f"[שגיאת רשת] {e}")
        return []

    if data.get("count", 0) > 0:
        logging.info(f"✅ נמצאו {data['count']} טריידים")
        return data["items"]
    logging.warning("❌ אין טריידים איכותיים כרגע.")
    return []

if __name__ == "__main__":
    logging.info("🔄 AlgoGPT Scan Runner – סריקה חיה")
    while True:
        find_best_trades(top=25)
        time.sleep(60)


