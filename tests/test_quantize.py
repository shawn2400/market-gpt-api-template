import math
from utils.quantize import (
    quantize_price,
    quantize_qty,
    ensure_min_qty,
    ensure_min_notional,
    clamp_decimals,
)

# פילטרים מדומים (כמו Exchange Info) – יציבים לטסטים
F = {"tick": 0.01, "step": 0.001, "minQty": 0.001, "minNotional": 5.0}


def test_quantize_price_floor():
    assert quantize_price(100.007, F, "down") == 100.00
    assert quantize_price(100.019, F, "down") == 100.01


def test_quantize_price_up():
    assert quantize_price(100.001, F, "up") == 100.01


def test_quantize_price_nearest():
    # 100.005 -> ל־100.01 (כי nearest)
    assert quantize_price(100.005, F, "nearest") == 100.01


def test_quantize_qty_floor():
    assert quantize_qty(0.0019, F) == 0.001
    assert quantize_qty(0.0574, F) == 0.057


def test_ensure_min_qty():
    # מתחת למינימום – מעלה ל־minQty (תוך כיבוד step)
    assert ensure_min_qty(0.0, F) == 0.001
    assert ensure_min_qty(0.0004, F) == 0.001
    # מעל מינימום – נשאר לאחר קוונטיזציה
    assert ensure_min_qty(0.0022, F) == 0.002


def test_ensure_min_notional():
    # מחיר 10$, minNotional=5 => הכמות המינימלית ~0.5, עם step 0.001 → 0.5 יעוגל ל־0.5
    assert ensure_min_notional(0.1, 10.0, F) == 0.5
    # אם כבר מספיק גבוה – יוחזר לאחר קוונטיזציה
    assert ensure_min_notional(1.2345, 10.0, F) == 1.234


def test_clamp_decimals():
    v = clamp_decimals(1.234567, 3)
    assert math.isclose(v, 1.235, rel_tol=0, abs_tol=1e-12)
