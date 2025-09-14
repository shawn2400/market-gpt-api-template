# FILE: utils/timehelpers.py
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

TZ_IL = ZoneInfo("Asia/Jerusalem")

def now_ts(fmt_il: str = "%d/%m/%Y %H:%M:%S %Z",
           fmt_utc: str = "%Y-%m-%d %H:%M:%S UTC"):
    """
    Returns (ts_il, ts_utc) formatted timestamps.
    """
    now_il = datetime.now(TZ_IL)
    ts_il = now_il.strftime(fmt_il)
    ts_utc = now_il.astimezone(timezone.utc).strftime(fmt_utc)
    return ts_il, ts_utc
