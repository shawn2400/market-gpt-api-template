# utils/net_guard.py
import time
import random
import logging
from contextlib import suppress

logger = logging.getLogger("algogpt.net_guard")

try:
    from httpx import ReadTimeout, ConnectTimeout  # type: ignore
except Exception:  # אם httpx לא קיים בסביבה הספציפית
    class ReadTimeout(Exception): ...
    class ConnectTimeout(Exception): ...

def _is_retryable(exc: Exception) -> bool:
    # שגיאות רשת/טיים-אאוט/429/5xx
    if isinstance(exc, (ReadTimeout, ConnectTimeout)):
        return True
    status = getattr(exc, "status_code", None)
    if isinstance(status, int) and (status == 429 or 500 <= status <= 599):
        return True
    s = str(exc)
    return ("429" in s) or ("timeout" in s.lower()) or ("temporarily" in s.lower())

def with_retries(fn, *, tries: int = 4, base_ms: int = 200, max_ms: int = 3200, on_error=None):
    """
    מריץ fn() עם ריטריים אקספוננציאליים + jitter.
    מחזיר את תוצאת fn או מעלה את החריג האחרון (אחרי כל הנסיונות).
    """
    last_exc = None
    for i in range(tries):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001
            last_exc = e
            if not _is_retryable(e):
                raise
            sleep_ms = min(max_ms, base_ms * (2 ** i))
            # jitter 20%±
            sleep_ms = int(sleep_ms * (0.9 + random.random() * 0.2))
            if callable(on_error):
                with suppress(Exception):
                    on_error(i + 1, e, sleep_ms)
            time.sleep(sleep_ms / 1000.0)
    # נכשל אחרי כל הנסיונות
    assert last_exc is not None
    raise last_exc
