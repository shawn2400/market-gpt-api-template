from utils.position_sizing import auto_qty, ensure_final_qty
import os

def test_auto_qty_disabled_by_default(monkeypatch):
    # ברירת מחדל AUTO_QTY_ENABLE=0 → None
    assert auto_qty("BTCUSDT", 10000.0, 10) is None

def test_auto_qty_min_notional(monkeypatch):
    monkeypatch.setenv("AUTO_QTY_ENABLE", "1")
    monkeypatch.setenv("AUTO_QTY_BUDGET_USDT", "50")
    monkeypatch.setenv("AUTO_QTY_MARGIN_BUFFER_PCT", "0.0")
    # MIN_NOTIONAL_USDT=5, מחיר 10 → צריך לפחות 0.5 יח'
    monkeypatch.setenv("MIN_NOTIONAL_USDT", "5")
    q = auto_qty("BTCUSDT", 10.0, 1)
    assert q is not None and q >= 0.5

def test_ensure_final_qty_when_missing(monkeypatch):
    monkeypatch.setenv("AUTO_QTY_ENABLE", "1")
    monkeypatch.setenv("AUTO_QTY_BUDGET_USDT", "20")
    monkeypatch.setenv("AUTO_QTY_MARGIN_BUFFER_PCT", "0.1")
    ticket = {"symbol": "BTCUSDT", "leverage": 5}
    out = ensure_final_qty(ticket, symbol_price=10000.0)
    # מינימום step לפי ברירת מחדל 0.001 → אמור לקבוע qty>0
    assert out.get("qty", 0) > 0
    assert out.get("leverage", 0) == 5 or out.get("leverage", 0) > 0
