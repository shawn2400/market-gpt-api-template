# routes/guard_smoke.py
from __future__ import annotations
import os, time
from typing import Any, Dict, List, Optional
from contextlib import suppress

import httpx
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse

router = APIRouter(tags=["guard-smoke"])

# --- Env / Telegram ---
BOT_TOKEN     = (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
ADMIN_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID") or os.getenv("ADMIN_CHAT_ID")
WORKING_TYPE  = (os.getenv("STOP_WORKING_TYPE") or "MARK_PRICE").strip().upper()

# --- Import guard (same helper the app uses) ---
with suppress(Exception):
    from utils.guard_stop import ensure_protective_stop  # type: ignore

def _has_active_stop_reduce_only(orders: List[Dict[str, Any]]) -> bool:
    """
    Detect active protective stop on current orders: STOP/STOP_MARKET/STOP_LOSS_LIMIT + reduceOnly=true.
    """
    for o in (orders or []):
        typ = str(o.get("type","")).upper()
        if "STOP" in typ:  # covers STOP, STOP_MARKET, STOP_LOSS_LIMIT
            if str(o.get("reduceOnly","false")).lower() == "true":
                return True
    return False

async def _send_tg(text: str) -> Dict[str, Any]:
    if not BOT_TOKEN or not ADMIN_CHAT_ID:
        return {"ok": False, "skipped": True}
    payload = {
        "chat_id": int(ADMIN_CHAT_ID) if str(ADMIN_CHAT_ID).isdigit() else ADMIN_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    async with httpx.AsyncClient(timeout=12.0) as cli:
        r = await cli.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage", json=payload)
        with suppress(Exception):
            return r.json()
        return {"ok": False, "status": r.status_code, "text": r.text}

def _fetch_open_orders(cli, symbol: str) -> List[Dict[str, Any]]:
    with suppress(Exception):
        return cli.futures_get_open_orders(symbol=symbol) or []
    return []

def _align_position_mode(cli) -> None:
    mode_override = (os.getenv("POSITION_MODE_OVERRIDE","") or "").strip().lower()
    with suppress(Exception):
        if mode_override in ("hedge","dual","dual_side","dual_side_position","dualposition"):
            cli.futures_change_position_mode(dualSidePosition="true")
        elif mode_override in ("oneway","one_way","single","single_side","oneside"):
            cli.futures_change_position_mode(dualSidePosition="false")

@router.get("/guard/smoke/run", summary="Smoke-run protective stop on WATCHLIST; Telegram only if emergency placed")
async def guard_smoke_run(
    symbols: Optional[str] = Query(None, description="CSV override; default WATCHLIST"),
    notify_tg: bool = Query(True, description="Notify Telegram only when emergency SL was placed"),
) -> JSONResponse:
    # --- Inputs / symbols
    syms = [s.strip().upper() for s in (symbols.split(",") if symbols else (os.getenv("WATCHLIST","") or "").split(",")) if s.strip()]
    if not syms:
        raise HTTPException(status_code=400, detail="no symbols to run on (WATCHLIST empty and no override given)")

    # --- Binance client
    try:
        from binance.client import Client  # type: ignore
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"binance import failed: {e}")
    api_key = (os.getenv("BINANCE_API_KEY") or "").strip()
    api_sec = (os.getenv("BINANCE_API_SECRET") or "").strip()
    if not api_key or not api_sec:
        raise HTTPException(status_code=500, detail="BINANCE keys missing")
    cli = Client(api_key, api_sec)
    _align_position_mode(cli)

    results: Dict[str, Any] = {}
    emergencies: List[str] = []

    for sym in syms:
        # 1) snapshot before
        before = _fetch_open_orders(cli, sym)
        had_before = _has_active_stop_reduce_only(before)

        # 2) run guard (prefer quantities mode; working type inferred from env)
        emergency = False
        with suppress(Exception):
            # ensure_protective_stop is best-effort; returns optional status
            ret = ensure_protective_stop(sym, prefer_mode="quantities")
            # consider truthy/flags as hint, but we always validate with after-snapshot below
            if ret and isinstance(ret, dict) and any(ret.get(k) for k in ("placed", "emergency", "created", "ok")):
                emergency = True

        # 3) snapshot after
        after = _fetch_open_orders(cli, sym)
        has_after = _has_active_stop_reduce_only(after)

        # 4) decide if emergency happened (no SL -> SL now)
        if (not had_before) and has_after:
            emergency = True

        if emergency:
            emergencies.append(sym)

        results[sym] = {
            "had_active_sl_before": had_before,
            "has_active_sl_after": has_after,
            "emergency_placed": bool(emergency),
            "working_type": WORKING_TYPE,
            "checked_at": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()) + "Z",
        }

    # --- Telegram only if at least one emergency happened
    if notify_tg and emergencies:
        lines = ["🧯 <b>Protective Smoke-Run</b>", "בוצעו SL-חירום בסימבולים הבאים:"]
        for s in emergencies:
            lines.append(f"• <code>{s}</code>")
        await _send_tg("\n".join(lines))

    return JSONResponse({"ok": True, "emergencies": emergencies, "results": results})

