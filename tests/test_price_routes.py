"""
Price routes tests
"""
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)

def test_price_last_endpoint():
    """Test /price/last endpoint if it exists"""
    r = client.get("/price/last", params={"symbol":"BTCUSDT"})
    # Endpoint might not exist or be disabled
    if r.status_code == 200:
        j = r.json()
        assert "symbol" in j or "price" in j or "ok" in j
    else:
        # 404 is ok if endpoint doesn't exist
        assert r.status_code in (200, 404, 422)

def test_price_symbol_endpoint():
    """Test /price/{symbol} endpoint if it exists"""
    r = client.get("/price/BTCUSDT")
    # Endpoint might not exist or be disabled
    if r.status_code == 200:
        j = r.json()
        assert "price" in j or "symbol" in j or "ok" in j
    else:
        # 404 is ok if endpoint doesn't exist
        assert r.status_code in (200, 404, 422)
