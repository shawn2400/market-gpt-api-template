def round_to_precision(value: float, precision: int) -> float:
    """
    מעגל ערך עשרוני לפי רמת הדיוק שנבחרה.
    """
    return round(value, precision)

def get_precision_info(symbol: str) -> dict:
    """
    פונקציית דמה שמחזירה רמות דיוק לטסטים.
    """
    return {
        "pricePrecision": 2,
        "quantityPrecision": 3
    }
















