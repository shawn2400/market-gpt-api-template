# test_precision.py
from utils.precision_utils import round_to_precision, get_precision_info

def main():
    # בדיקה של העיגול
    x = 123.456789
    rounded = round_to_precision(x, 2)
    print(f"round_to_precision({x}, 2) -> {rounded}  (צפוי: 123.46)")

    # בדיקה של ה־precision info
    sym = "BTCUSDT"
    info = get_precision_info(sym)
    print(f"get_precision_info('{sym}') -> {info}  (צפוי: dict עם pricePrecision ו־quantityPrecision)")

if __name__ == "__main__":
    main()

