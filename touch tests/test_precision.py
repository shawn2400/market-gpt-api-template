from utils.precision_utils import round_to_precision, get_precision_info

def test_round_to_precision():
    assert round_to_precision(1.2345, 2) == 1.23

def test_get_precision_info_keys():
    info = get_precision_info("BTCUSDT")
    assert "pricePrecision" in info
    assert "quantityPrecision" in info














