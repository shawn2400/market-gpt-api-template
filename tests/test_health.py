"""
Health check tests - use TestClient instead of HTTP
"""
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)

def test_health():
    """Test /health endpoint"""
    r = client.get("/health")
    assert r.status_code == 200
    data = r.json()
    assert "ok" in data or "status" in data

def test_readyz():
    """Test /readyz endpoint"""
    r = client.get("/readyz")
    assert r.status_code == 200
    data = r.json()
    assert "ok" in data or "ready" in data
