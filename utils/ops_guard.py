# utils/ops_guard.py
from __future__ import annotations
import os, time, logging
from collections import deque
from typing import Optional

logger = logging.getLogger("algogpt.ops_guard")

# ===== ENV / Switches =====
OPS_ENABLE = os.getenv("OPS_ENABLE", "1").lower() in ("1","true","yes","on")

# Alerts
OPS_TTL_ALERT_SEC = float(os.getenv("OPS_TTL_ALERT_SEC", "10"))
OPS_TIMEOUT_BURST_N = int(os.getenv("OPS_TIMEOUT_BURST_N", "3"))
OPS_TIMEOUT_BURST_WINDOW_SEC = int(os.getenv("OPS_TIMEOUT_BURST_WINDOW_SEC", "60"))
OPS_ALERT_COOLDOWN_SEC = int(os.getenv("OPS_ALERT_COOLDOWN_SEC", "120"))

# Degrade Mode thresholds
OPS_DEGRADE_TTL_SEC = float(os.getenv("OPS_DEGRADE_TTL_SEC", "10"))
OPS_DEGRADE_WS_RECONNECTS = int(os.getenv("OPS_DEGRADE_WS_RECONNECTS", "6"))

# Notifiers (אופציונלי)
try:
    from utils.telegram_notifier import notify_error, notify_info
except Exception:
    async def notify_error(msg: str): return None
    async def notify_info(msg: str): return None

# State
_degrade_active: bool = False
_timeout_hits: deque[float] = deque(maxlen=200)
_last_alert_ts: dict[str, float] = {}

def _cooldown(key: str, sec: int) -> bool:
    now = time.time()
    last = _last_alert_ts.get(key, 0.0)
    if now - last >= sec:
        _last_alert_ts[key] = now
        return True
    return False

async def ops_tick(
    *,
    ws_reconnects: Optional[int] = None,
    price_ttl_sec: Optional[float] = None,
    exec_batch_timeout: bool = False,
) -> None:
    """
    נקודת איסוף רכה (לא שוברת קוד):
      - TTL Alerts
      - Timeout Burst Alerts
      - Degrade Mode ON/OFF (MARK_PRICE בלבד + החמרת שערי sanity)
    """
    if not OPS_ENABLE:
        return

    now = time.time()

    # Timeout-burst bookkeeping
    if exec_batch_timeout:
        _timeout_hits.append(now)

    # 1) TTL Alerts
    if price_ttl_sec is not None and price_ttl_sec > OPS_TTL_ALERT_SEC:
        if _cooldown("ttl_alert", OPS_ALERT_COOLDOWN_SEC):
            await notify_error(f"⚠️ WS price TTL גבוה: {price_ttl_sec:.1f}s — יתכן שהזרם לא רענן.")

    # 2) Timeout-burst Alerts
    if OPS_TIMEOUT_BURST_N > 0:
        burst = sum(1 for t in _timeout_hits if now - t <= OPS_TIMEOUT_BURST_WINDOW_SEC)
        if burst >= OPS_TIMEOUT_BURST_N and _cooldown("timeout_burst", OPS_ALERT_COOLDOWN_SEC):
            await notify_error(f"⚠️ עומס בסורק: {burst} timeouts ב-{OPS_TIMEOUT_BURST_WINDOW_SEC}s.")

    # 3) Degrade Mode (on/off)
    unhealthy = False
    if price_ttl_sec is not None and price_ttl_sec > OPS_DEGRADE_TTL_SEC:
        unhealthy = True
    if ws_reconnects is not None and ws_reconnects >= OPS_DEGRADE_WS_RECONNECTS:
        unhealthy = True

    global _degrade_active
    if unhealthy and not _degrade_active:
        _degrade_active = True
        # החמרת שערים + עבודה על MARK_PRICE בלבד
        os.environ["FEAT_MARK_INDEX_SANITY"] = "1"
        os.environ["BINANCE_WORKING_TYPE"] = "MARK_PRICE"
        logger.warning({"event": "degrade_on", "ttl": price_ttl_sec, "reconnects": ws_reconnects})
        if _cooldown("degrade_on", OPS_ALERT_COOLDOWN_SEC):
            await notify_error("🚨 Degrade Mode ON — מעבר ל-MARK_PRICE בלבד + Sanity Gate הוחמר.")
    elif _degrade_active and not unhealthy:
        _degrade_active = False
        logger.info({"event": "degrade_off"})
        if _cooldown("degrade_off", OPS_ALERT_COOLDOWN_SEC):
            await notify_info("✅ Degrade Mode OFF — חזרה למצב עבודה רגיל.")


