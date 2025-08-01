# tests/test_precision.py
from utils.precision_utils import round_to_precision, get_precision_info

def test_round_to_precision():
    assert round_to_precision(123.456789, 2) == 123.46

def test_get_precision_info():
    info = get_precision_info("BTCUSDT")
    assert isinstance(info, dict)
    assert "pricePrecision" in info and "quantityPrecision" in info




