# utils/anti_spam.py
import os, json, time, threading

_PATH = "/tmp/tg_cooldown.json"
_LOCK = threading.Lock()
_COOLDOWN_SEC = int(os.getenv("TG_COOLDOWN_SEC", "1800"))  # 30m default

def _load():
    try:
        with open(_PATH, "r") as f:
            return json.load(f)
    except Exception:
        return {}

def _save(data):
    tmp = _PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f)
    os.replace(tmp, _PATH)

def should_gate(key: str, cooldown: int | None = None) -> bool:
    """Return True if allowed to send now (cooldown passed), else False."""
    now = time.time()
    cd = _COOLDOWN_SEC if cooldown is None else int(cooldown)
    with _LOCK:
        data = _load()
        last = data.get(key)
        if last and now - float(last) < cd:
            return False
        data[key] = now
        _save(data)
        return True

def telegram_send_guarded(send_func, text: str, key: str, cooldown: int | None = None, **kw) -> bool:
    """
    TG_SILENT=1 -> suppress all.
    Gate by (key, cooldown). Returns True if actually sent.
    """
    if os.getenv("TG_SILENT") == "1":
        return False
    if not should_gate(key, cooldown=cooldown):
        return False
    try:
        send_func(text, **kw)
        return True
    except Exception:
        return False

def notify_once(send_func, symbol: str, etype: str, text: str, suffix: str = "", cooldown: int | None = None, **kw) -> bool:
    """
    Stable dedupe key: SYMBOL:EVENT[:SUFFIX]
    Used to avoid repeated BE/SL messages for same rounded price.
    """
    key = f"{symbol}:{etype}" + (f":{suffix}" if suffix else "")
    return telegram_send_guarded(send_func, text, key, cooldown=cooldown, **kw)
