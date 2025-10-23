import os, json, time, threading

# Persist simple anti-spam state on disk (atomic write)
PATH = "/tmp/tg_cooldown.json"
LOCK = threading.Lock()
COOLDOWN_SEC = int(os.getenv("TG_COOLDOWN_SEC", "1800"))  # default: 30m

def _load():
    try:
        with open(PATH, "r") as f:
            return json.load(f)
    except Exception:
        return {}

def _save(data):
    tmp = PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f)
    os.replace(tmp, PATH)

def should_gate(key: str, cooldown: int = COOLDOWN_SEC) -> bool:
    """
    Return True if we should send now (cooldown passed), False otherwise.
    """
    now = time.time()
    with LOCK:
        data = _load()
        last = data.get(key)
        if last and now - float(last) < cooldown:
            return False
        data[key] = now
        _save(data)
        return True

def telegram_send_guarded(send_func, text: str, key: str, cooldown: int = COOLDOWN_SEC, **kw) -> bool:
    """
    Gate + global silent switch. Returns True if actually sent.
    TG_SILENT=1 -> suppress everything.
    """
    if os.getenv("TG_SILENT") == "1":
        return False
    if not should_gate(key, cooldown=cooldown):
        return False
    send_func(text, **kw)
    return True

def notify_once(send_func, symbol: str, etype: str, text: str, key_suffix: str = "", cooldown: int = COOLDOWN_SEC, **kw) -> bool:
    """
    Convenience: stable key like SYMBOL:EVENT[:SUFFIX]
    Example: notify_once(telegram_send, "BTCUSDT", "BE_ARMED", msg, key_suffix="109065.0")
    """
    key = f"{symbol}:{etype}" + (f":{key_suffix}" if key_suffix else "")
    return telegram_send_guarded(send_func, text, key, cooldown=cooldown, **kw)
