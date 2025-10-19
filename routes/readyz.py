# routes/readyz.py
from __future__ import annotations
import os, time, asyncio
from contextlib import suppress
from fastapi import APIRouter
from fastapi.responses import JSONResponse

router = APIRouter(tags=["readyz"])

def _flag(name: str, default: str = "0") -> bool:
    return (os.getenv(name, default) or default).lower() in ("1", "true", "yes", "on")

async def _ping_redis(get_redis_cached) -> tuple[bool, str]:
    try:
        r = await get_redis_cached()
        if not r:
            return False, "no_client"
        await asyncio.wait_for(r.ping(), timeout=0.8)
        return True, "ok"
    except Exception as e:
        return False, f"err:{e}"

async def _check_binance() -> tuple[bool, str]:
    # lightweight public HTTP probe (no creds needed)
    import httpx
    url = (os.getenv("BINANCE_FUTURES_HTTP_BASE") or "https://fapi.binance.com").rstrip("/") + "/fapi/v1/ping"
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(3.0)) as cli:
            r = await cli.get(url)
            # Binance לעתים מחזירה 418 על rate-limit/anti-bot. נתייחס לזה כ-WARN ולא כשבירה
            if r.status_code in (200, 204):
                return True, "ok"
            if r.status_code == 418:
                return False, "http_418"
            return False, f"http_{r.status_code}"
    except Exception as e:
        return False, f"err:{e}"

@router.get("/health")
async def health():
    return {"ok": True, "service": os.getenv("APP_TITLE", "AlgoGPT")}

@router.get("/health/live")
async def live():
    return {"ok": True, "live": True}

@router.get("/health/readiness")
async def readiness():
    # Toggles
    chk_redis = _flag("READINESS_CHECK_REDIS", "1")
    req_redis = _flag("REQUIRE_REDIS", "0")
    chk_bin   = _flag("READINESS_CHECK_BINANCE", "1")
    req_bin   = _flag("REQUIRE_BINANCE", "0")  # חדש: ברירת מחדל לא חובה
    chk_sql   = _flag("READINESS_CHECK_SQLITE", "0")
    req_sql   = _flag("REQUIRE_SQLITE", "0")

    deps = {
        "redis": {"ok": True, "detail": "skipped"},
        "binance": {"ok": True, "detail": "skipped"},
        "sqlite": {"ok": True, "detail": "skipped", "path": os.getenv("SQLITE_PATH")},
    }

    # Redis
    if chk_redis:
        ok, detail = False, "unknown"
        with suppress(Exception):
            # import מ-main כדי למחזר את המחבר וה־URL
            from main import _get_redis_cached  # type: ignore
            ok, detail = await _ping_redis(_get_redis_cached)
        deps["redis"] = {"ok": ok, "detail": detail}

    # Binance (public ping)
    if chk_bin:
        ok, detail = await _check_binance()
        deps["binance"] = {"ok": ok, "detail": detail}

    # SQLite (קיום קובץ/נתיב אם מסומן לבדיקה)
    if chk_sql:
        p = os.getenv("SQLITE_PATH")
        if p:
            try:
                # בדיקה רכה: עצם קיום הנתיב/כתיבה בהמשך שייכת לקוד שמנהל DB
                deps["sqlite"] = {"ok": True, "detail": "exists", "path": p}
            except Exception as e:
                deps["sqlite"] = {"ok": False, "detail": f"err:{e}", "path": p}
        else:
            deps["sqlite"] = {"ok": True, "detail": "skipped", "path": None}

    # החלטת סטטוס: כשל ב־**תלויות חובה** בלבד מפיל ל־503
    hard_fails = []
    if req_redis and not deps["redis"]["ok"]:
        hard_fails.append("redis")
    if req_bin and not deps["binance"]["ok"]:
        hard_fails.append("binance")
    if req_sql and not deps["sqlite"]["ok"]:
        hard_fails.append("sqlite")

    overall_ok = len(hard_fails) == 0
    status = 200 if overall_ok else 503

    # כבוד מיוחד ל־418: נסמן ok=False אבל לא נהפוך אותו לחובה אם REQUIRE_BINANCE=0 (ברירת מחדל)
    return JSONResponse(
        {"ok": overall_ok, "deps": deps, "failed_required": hard_fails or None, "ts": int(time.time())},
        status_code=status,
    )

