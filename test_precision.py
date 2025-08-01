from utils.precision_utils import round_to_precision, get_precision_info

def test_round_to_precision_simple():
    assert round_to_precision(123.456789, 2) == 123.46

def test_round_to_precision_negative():
    assert round_to_precision(-1.2345, 3) == -1.235

def test_get_precision_info_structure():
    info = get_precision_info("BTCUSDT")
    assert isinstance(info, dict)
    assert "pricePrecision" in info
    assert "quantityPrecision" in info
    assert isinstance(info["pricePrecision"], int)
    assert isinstance(info["quantityPrecision"], int)








