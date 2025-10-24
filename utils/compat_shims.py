# utils/compat_shims.py
from typing import Any, Dict

# --- anti-replay / security (כאשר חתימות מבוטלות) ---
def verify_hmac(*args, **kwargs) -> bool:
    # חתימה מבוטלת ע"י ENV, נחזיר True כדי לא להפיל import/routes
    return True

def build_signature_headers(*args, **kwargs) -> Dict[str, str]:
    # כשלא צריך חתימות – נחזיר כותרות ריקות
    return {}

# --- executor ---
def is_executor_running() -> bool:
    # עד שהפונקציה האמיתית תתוקן
    return True

# --- binance client shims ---
def place_limit_order(*args, **kwargs) -> Dict[str, Any]:
    # הנחיה: החלף בהמשך ל- utils.binance_client.place_limit_order האמיתי
    raise NotImplementedError("place_limit_order shim – implement real client")

def get_order(*args, **kwargs) -> Dict[str, Any]:
    raise NotImplementedError("get_order shim – implement real client")

# --- indicators ext ---
def advanced_indicators(*args, **kwargs) -> Dict[str, Any]:
    # עד שיהיה מודול אמיתי
    return {}

# --- storage shim ל-news ---
class _DummyStorage:
    def get(self, *a, **k): return None
    def put(self, *a, **k): return True

storage = _DummyStorage()
