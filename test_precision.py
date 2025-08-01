# test_precision.py
from utils.precision_utils import round_to_precision, get_precision_info

print(round_to_precision(1.234567, 2), get_precision_info("BTCUSDT"))
