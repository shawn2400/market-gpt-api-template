# tests/test_price_routes.py
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)

def test_price_last_endpoint():
    r = client.get("/price/last", params={"symbol":"BTCUSDT"})
    assert r.status_code == 200
    j = r.json()
    assert j["ok"] is True
    assert j["symbol"] == "BTCUSDT"

def test_price_symbol_endpoint():
    r = client.get("/price/BTCUSDT")
    assert r.status_code == 200
    j = r.json()
    assert j["ok"] is True
