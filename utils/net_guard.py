# utils/net_guard.py
import time, random
from contextlib import suppress
from httpx import ReadTimeout, ConnectTimeout
from binance.error import BinanceAPIException  # אם קיים אצלכם

def with_retries(fn, *, tries=4, base_ms=200, max_ms=3200, on_error=None):
    """
    מריץ fn() עם ריטריים אקספוננציאליים + jitter. מחזיר ערך fn או מעלה חריג אחרון.
    """
    last = None
    for i in range(tries):
        try:
            return fn()
        except (ReadTimeout, ConnectTimeout) as e:
            last = e
        except Exception as e:
            # שגיאות זמניות של בורסה
            if '429' in str(e) or '5' == str(getattr(e, 'status_code', '')).startswith('5'):
                last = e
            else:
                raise
        # backoff + jitter
        sleep_ms = min(max_ms, base_ms * (2 ** i))
        sleep_ms = int(sleep_ms * (0.8 + random.random()*0.4))
        if callable(on_error):
            with suppress(Exception):
                on_error(i+1, last, sleep_ms)
        time.sleep(sleep_ms/1000.0)
    # אם נכשל אחרי כל הניסיונות – אל תפיל את הלופ: תחזיר ערך "ריק" על פי הקונטקסט
    raise last or RuntimeError("request failed")
