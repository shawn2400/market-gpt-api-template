import pytest
from utils.precision_utils import round_to_precision, get_precision_info

def test_round_to_precision():
    assert round_to_precision(1.2345, 2) == 1.23
    assert round_to_precision(123.456789, 4) == 123.4568

def test_get_precision_info_structure():
    info = get_precision_info("BTCUSDT")
    assert isinstance(info, dict)
    # וידא שהמפתחות שהגדרת קיימים
    assert "pricePrecision" in info
    assert "quantityPrecision" in info
    # ודא שהם מסוג מספרי
    assert isinstance(info["pricePrecision"], int)
    assert isinstance(info["quantityPrecision"], int)
