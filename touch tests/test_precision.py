import pytest
from utils.precision_utils import round_to_precision, get_precision_info

def test_round_to_precision():
    # בדיקה פשוטה של עיגול
    assert round_to_precision(1.2345, 2) == 1.23

def test_get_precision_info_keys():
    # וידוא שהפונקציה מחזירה מילון עם המפתחות הנכונים
    info = get_precision_info("BTCUSDT")
    assert isinstance(info, dict)
    assert "pricePrecision" in info
    assert "quantityPrecision" in info















