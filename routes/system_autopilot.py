# routes/system_autopilot.py
from __future__ import annotations
import os, time, asyncio, logging
from typing import Dict, Any, Optional

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

# auth אופציונלי (אם יש אצלך)
try:
    from utils.auth import require_api_key
    _deps = [Depends(require_api_key)]
except Exception:
    _deps = []

logger = logging.getLogger("algogpt.autopilot")
router = APIRouter(prefix="/system/autopilot", tags=["System"], dependencies=_deps)

# --- ייבוא דינמי כדי שנתערב בזמן ריצה ---
# נעדכן ישירות משתנים גלובליים של הסורק
try:
    from utils import auto_executor as AE
except Exception:
    AE = None  # בסביבות DEV אפשר שאין קובץ

# שליחת טלגרם (פשוטה)
import httpx
TG_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TG_CHAT  = os.getenv("ADMIN_CHAT_ID", "").strip()

AUTOPILOT_ENABLED = True
STATE: Dict[str, Any] = {
    "enabled": True,
    "last_check": None,
    "last_action": None,
    "cool_since": None,
    "applied": False,
    "reason": None,
    "actions": {},
    "original": {},   # לשחזור
}

# מדיניות
CHECK_INTERVAL_SEC = int(os.getenv("AUTOPILOT_CHECK_SEC", "30"))
MEM_HI_PCT = 85.0
CORES_WARN = 0.7   # load1/cores
CORES_CRIT = 1.2

# גבולות שינוי
MIN_SCAN_CONCURRENCY = 2
MAX_SCAN_INTERVAL    = 180   # שניות
TTL_HARD             = 1800  # שניות exchangeInfo/klines ttl "גבוה"

# תיעדוף שינוי: קודם מקביליות, אח"כ מרווח סריקה, אח"כ TTL
def _level_for(load1: float, cores: int, used_pct: float) -> str:
    if cores <= 0:
        cores = 1
    ratio = load1 / float(cores)
    if used_pct >= MEM_HI_PCT or ratio >= CORES_CRIT:
        return "crit"
    if ratio >= CORES_WARN:
        return "warn"
    return "ok"

def _read_meminfo() -> float:
    try:
        with open("/proc/meminfo","r") as f:
            d = {}
            for line in f:
                k, v = line.split(":",1)
                d[k.strip()] = int(v.strip().split()[0])
        total = d.get("MemTotal", 0)
        avail = d.get("MemAvailable", 0)
        used_pct = (1 - (avail / total)) * 100 if total else 0.0
        return used_pct
    except Exception:
        return 0.0

def _loadavg():
    try:
        return os.getloadavg()
    except Exception:
        return (0.0, 0.0, 0.0)

def _cores():
    try:
        return os.cpu_count() or 1
    except Exception:
        return 1

async def _tg_notify(text: str):
    if not TG_TOKEN or not TG_CHAT:
        return
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    payload = {"chat_id": int(TG_CHAT), "text": text, "parse_mode": "Markdown"}
    try:
        async with httpx.AsyncClient(timeout=8.0) as cli:
            await cli.post(url, json=payload)
    except Exception as e:
        logger.warning(f"[autopilot] telegram notify failed: {e}")

def _snapshot_current() -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    if AE:
        out["SCAN_CONCURRENCY"] = getattr(AE, "SCAN_CONCURRENCY", None)
        out["SCAN_INTERVAL"]    = getattr(AE, "SCAN_INTERVAL", None)
    out["EXCHANGE_INFO_TTL_SEC"] = int(os.getenv("EXCHANGE_INFO_TTL_SEC","900"))
    return out

def _apply_throttle(reason: str) -> Dict[str, Any]:
    actions = {}
    if AE:
        # שמור פעם ראשונה
        if not STATE["original"]:
            STATE["original"] = _snapshot_current()

        # 1) הורד מקביליות
        cur_conc = int(getattr(AE, "SCAN_CONCURRENCY", 4) or 4)
        new_conc = max(MIN_SCAN_CONCURRENCY, min(cur_conc, 4))
        if new_conc < cur_conc:
            setattr(AE, "SCAN_CONCURRENCY", new_conc)
            actions["SCAN_CONCURRENCY"] = {"from": cur_conc, "to": new_conc}

        # 2) הגדל מרווח סריקה
        cur_int = int(getattr(AE, "SCAN_INTERVAL", 60) or 60)
        new_int = min(MAX_SCAN_INTERVAL, max(cur_int, 75))
        if new_int > cur_int:
            setattr(AE, "SCAN_INTERVAL", new_int)
            actions["SCAN_INTERVAL"] = {"from": cur_int, "to": new_int}

    # 3) הגדל TTL
    cur_ttl = int(os.getenv("EXCHANGE_INFO_TTL_SEC","900"))
    new_ttl = max(cur_ttl, TTL_HARD)
    if new_ttl > cur_ttl:
        os.environ["EXCHANGE_INFO_TTL_SEC"] = str(new_ttl)
        actions["EXCHANGE_INFO_TTL_SEC"] = {"from": cur_ttl, "to": new_ttl}

    STATE.update({
        "applied": True,
        "last_action": int(time.time()),
        "actions": actions,
        "reason": reason,
    })
    return actions

def _revert_if_needed():
    if not STATE.get("applied") or not STATE.get("original"):
        return {}
    actions = {}
    orig = STATE["original"]

    if AE:
        cur_conc = int(getattr(AE, "SCAN_CONCURRENCY", 4) or 4)
        if orig.get("SCAN_CONCURRENCY") is not None and cur_conc != orig["SCAN_CONCURRENCY"]:
            setattr(AE, "SCAN_CONCURRENCY", int(orig["SCAN_CONCURRENCY"]))
            actions["SCAN_CONCURRENCY"] = {"to": orig["SCAN_CONCURRENCY"]}

        cur_int = int(getattr(AE, "SCAN_INTERVAL", 60) or 60)
        if orig.get("SCAN_INTERVAL") is not None and cur_int != orig["SCAN_INTERVAL"]:
            setattr(AE, "SCAN_INTERVAL", int(orig["SCAN_INTERVAL"]))
            actions["SCAN_INTERVAL"] = {"to": orig["SCAN_INTERVAL"]}

    cur_ttl = int(os.getenv("EXCHANGE_INFO_TTL_SEC","900"))
    if orig.get("EXCHANGE_INFO_TTL_SEC") is not None and cur_ttl != orig["EXCHANGE_INFO_TTL_SEC"]:
        os.environ["EXCHANGE_INFO_TTL_SEC"] = str(int(orig["EXCHANGE_INFO_TTL_SEC"]))
        actions["EXCHANGE_INFO_TTL_SEC"] = {"to": orig["EXCHANGE_INFO_TTL_SEC"]}

    if actions:
        STATE.update({"applied": False, "actions": actions, "reason": "reverted", "cool_since": int(time.time())})
    return actions

# --- לוגיקת מוניטור רקע ---
async def background_autopilot():
    await asyncio.sleep(3)
    logger.info("[autopilot] background started")
    while True:
        try:
            if not STATE["enabled"]:
                await asyncio.sleep(CHECK_INTERVAL_SEC)
                continue

            load1, _, _ = _loadavg()
            used_pct = _read_meminfo()
            lvl = _level_for(load1, _cores(), used_pct)
            STATE["last_check"] = int(time.time())

            if lvl == "crit":
                actions = _apply_throttle(reason=f"crit: load1={load1:.2f}, mem={used_pct:.1f}%")
                if actions:
                    txt = (
                        "🔴 *System Autopilot: CRIT*\n"
                        f"• load1={load1:.2f}, mem_used={used_pct:.1f}%\n"
                        f"• actions={actions}\n"
                        "המערכת האטה זמנית (TTL↑, מקביליות↓, מרווח↓) כדי למנוע חנק."
                    )
                    await _tg_notify(txt)
            elif lvl == "warn":
                # במצב warn לא נעשה עוד throttle אם כבר הוחל
                pass
            else:  # ok
                if STATE.get("applied"):
                    reverted = _revert_if_needed()
                    if reverted:
                        await _tg_notify("🟢 *System Autopilot*: שוחזרו הפרמטרים למצב רגיל.")

        except Exception as e:
            logger.warning(f"[autopilot] loop error: {e}")
        await asyncio.sleep(CHECK_INTERVAL_SEC)

# --- Endpoints ---

@router.get("/status")
async def status():
    info = {
        "enabled": STATE["enabled"],
        "applied": STATE["applied"],
        "actions": STATE.get("actions", {}),
        "reason": STATE.get("reason"),
        "original": STATE.get("original", {}),
        "last_check": STATE.get("last_check"),
        "last_action": STATE.get("last_action"),
        "cool_since": STATE.get("cool_since"),
        "scan_concurrency": getattr(AE, "SCAN_CONCURRENCY", None) if AE else None,
        "scan_interval": getattr(AE, "SCAN_INTERVAL", None) if AE else None,
        "ttl": int(os.getenv("EXCHANGE_INFO_TTL_SEC","900")),
    }
    return JSONResponse({"ok": True, "autopilot": info})

@router.post("/enable")
async def enable():
    STATE["enabled"] = True
    return {"ok": True, "enabled": True}

@router.post("/disable")
async def disable():
    STATE["enabled"] = False
    return {"ok": True, "enabled": False}

# קריאה מתוך main.py ב-startup:
async def start_autopilot():
    asyncio.create_task(background_autopilot())
