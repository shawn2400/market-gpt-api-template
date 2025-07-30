# utils/precision_utils.py
from utils.binance_client import client

def get_precision_info(symbol: str) -> dict:
    """
    מחזיר dict עם stepSize ו-minQty עבור הסימבול.
    """
    info = client.futures_exchange_info()
    for s in info['symbols']:
        if s['symbol'] == symbol:
            filters = s.get('filters', [])
            stepSize = 0.01
            minQty = 0.001
            for f in filters:
                if f['filterType'] == 'LOT_SIZE':
                    stepSize = float(f['stepSize'])
                    minQty = float(f['minQty'])
                    break
            return {"stepSize": stepSize, "minQty": minQty}
    # ברירת מחדל אם לא נמצא
    return {"stepSize": 0.01, "minQty": 0.001}
