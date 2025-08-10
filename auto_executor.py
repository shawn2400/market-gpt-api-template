# auto_executor.py
import asyncio
import logging
from typing import Optional

# קורא פרמטרים מהקונפיג
try:
    from utils import config
except Exception:
    class _Dummy:
        AUTO_RUN = False
        SCAN_INTERVAL = 60
    config = _Dummy()  # fallback בטוח

# דגלים/פרמטרים
_SCAN_INTERVAL = int(getattr(config, "SCAN_INTERVAL", 60))
_AUTO_RUN_BOOT = bool(getattr(config, "AUTO_RUN", False))

# ניתן להפעיל לוגיקת סריקות אמיתית בהמשך (כרגע NO-OP בטוח)
_ENABLE_REAL_SCANNER = False  # שנה ל-True רק כשמוכנים להפעיל סריקות חיות

_task: Optional[asyncio.Task] = None
_stop_evt: Optional[asyncio.Event] = None

async def _runner():
    """
    לולאת רקע בטוחה:
    - ברירת מחדל NO-OP (לא מבצעת פעולות כתיבה).
    - כשמחברים סורק אמיתי: עטוף ב-try/except כדי שלא יפיל את השרת.
    """
    global _stop_evt
    logging.info("[AUTO] background runner started (interval=%ss, real_scanner=%s)",
                 _SCAN_INTERVAL, _ENABLE_REAL_SCANNER)

    # טעינת מודולים כבדה רק אם באמת נדרש
    if _ENABLE_REAL_SCANNER:
        try:
            from utils.multi_tf_scanner import multi_tf_scan_with_ai  # noqa
        except Exception as e:
            logging.warning("[AUTO] scanner import failed -> falling back to NO-OP: %s", e)

    while _stop_evt and not _stop_evt.is_set():
        try:
            if _ENABLE_REAL_SCANNER:
                # דוגמה: הפעלת סריקה קלה (ללא כתיבה/טרייד)
                # results = await multi_tf_scan_with_ai(timeframes=("15m","1h"), markets=("futures",), min_quality=6, top=5)
                # logging.info("[AUTO] scan tick -> %d candidates", len(results or []))
                pass
            else:
                # NO-OP: שמירה על heartbeat בלוגים
                logging.debug("[AUTO] tick (noop)")
        except Exception as e:
            logging.warning("[AUTO] runner tick error (ignored): %s", e)
        # המתנה בין טיקים
        try:
            await asyncio.wait_for(_stop_evt.wait(), timeout=_SCAN_INTERVAL)
        except asyncio.TimeoutError:
            pass
        except Exception as e:
            logging.debug("[AUTO] wait error (ignored): %s", e)

    logging.info("[AUTO] background runner stopped")

def is_executor_running() -> bool:
    return bool(_task and not _task.done())

def start_executor() -> bool:
    """
    מפעיל את האקסקיוטור אם אינו פעיל. ניתן לקרוא גם מתוך endpoints (context של event loop).
    מחזיר True אם אחרי הקריאה האקסקיוטור רץ.
    """
    global _task, _stop_evt
    if _task and not _task.done():
        return True
    loop = asyncio.get_running_loop()
    _stop_evt = asyncio.Event()
    _task = loop.create_task(_runner())
    logging.info("[AUTO] executor started")
    return True

def stop_executor() -> bool:
    """
    עוצר את האקסקיוטור (לא חוסם עד שה-task מסתיים בפועל).
    """
    global _task, _stop_evt
    if _stop_evt and not _stop_evt.is_set():
        _stop_evt.set()
    if _task and _task.done():
        _task = None
    logging.info("[AUTO] executor stop requested")
    return True

# הפעלה אוטומטית בעליית השרת (רק אם הוגדר AUTO_RUN=true)
# הערה: הקריאה בפועל ל-start_executor תיעשה גם מ-main.py/startup.
if _AUTO_RUN_BOOT:
    try:
        # אם מייבאים את המודול לפני שהלופ רץ, לא נוכל ליצור task כאן.
        # לכן ההפעלה בפועל נעשית ב-main.py בתוך אירוע startup.
        logging.info("[AUTO] AUTO_RUN=true (startup will start executor)")
    except Exception as e:
        logging.debug("[AUTO] auto-run hint failed: %s", e)










































































