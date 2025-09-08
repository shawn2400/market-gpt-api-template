import os, httpx

BASE = os.getenv("BASE_URL", "http://localhost:10000")

def test_health():
    r = httpx.get(f"{BASE}/health", timeout=10)
    assert r.status_code == 200
    assert r.json().get("ok") is True

def test_readyz():
    r = httpx.get(f"{BASE}/readyz", timeout=10)
    assert r.status_code == 200
    assert "ok" in r.json()
