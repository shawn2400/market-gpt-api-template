import time

# מילון חדש שמכיל timestamps של עדכון מחיר (בתוך _on_message_multi)
live_timestamps: Dict[str, float] = {}

def _on_message_multi(ws, message):
    try:
        data = json.loads(message)
        if "data" in data and "s" in data["data"] and "p" in data["data"]:
            symbol = data["data"]["s"].upper()
            price = float(data["data"]["p"])
            live_prices[symbol] = price
            live_timestamps[symbol] = time.time()  # עדכון זמן קבלה
            logging.debug(f"[WS-MULTI] {symbol} price updated: {price}")
        else:
            logging.debug(f"[WS-MULTI] Received: {data}")
    except Exception as e:
        logging.warning(f"[WS-MULTI] Failed to parse message: {e}")

def is_price_fresh(symbol: str, max_age_sec: int = 10) -> bool:
    """
    האם מחיר WS עודכן ב־max_age_sec שניות אחרונות?
    """
    now = time.time()
    ts = live_timestamps.get(symbol.upper())
    return ts is not None and (now - ts) < max_age_sec














