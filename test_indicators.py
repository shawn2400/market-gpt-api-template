import requests

BASE_URL = "http://localhost:10000"  # או https://algogpt-docker.onrender.com

def test_indicators():
    url = f"{BASE_URL}/indicators/BNBUSDT"
    resp = requests.get(url)
    assert resp.status_code == 200, f"Failed! {resp.text}"
    data = resp.json()
    print("✅ Indicators response:", data)

if __name__ == "__main__":
    test_indicators()
