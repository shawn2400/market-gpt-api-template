# routes/ops_approve.py
from __future__ import annotations
from fastapi import APIRouter, Query, Request
from typing import Optional, Dict, Any
import os
import asyncio

router = APIRouter(prefix="/ops", tags=["Ops"])  # בכוונה ללא דרישת טוקן (ציבורי) – כמו ב-main.py

# קביעות ברירת מחדל לביצוע הטרייד אחרי אישור
OPS_DEFAULTS = {
    "market": os.getenv("OPS_DEFAULT_MARKET", "futures"),
    "account_id": os.getenv("OPS_DEFAULT_ACCOUNT", "main"),
    "budget": float(os.getenv("OPS_DEFAULT_BUDGET", "10")),
    "leverage": int(os.getenv("OPS_DEFAULT_LEVERAGE", "10")),
    "grids": int(os.getenv("OPS_DEFAULT_GRIDS", "3")),
    "dry_run": (os.getenv("OPS_DRY_RUN", "0").lower() in ("1", "true", "yes", "on")),
    "side_spot_buy": os.getenv("OPS_SPOT_BUY", "BUY"),     # עבור spot
    "side_spot_sell": os.getenv("OPS_SPOT_SELL", "SELL"),
    "side_fut_long": os.getenv("OPS_FUT_LONG", "LONG"),    # עבור futures
    "side_fut_short": os.getenv("OPS_FUT_SHORT", "SHORT"),
}

# אסימון פנימי עבור קריאה עצמית ל-/grid/trade (מוגן)
INTERNAL_TOKEN = os.getenv("OPS_INTERNAL_TOKEN", os.getenv("API_TOKEN", os.getenv("TOKEN", ""))).strip()


async def _place_grid_trade(
    base_url: str,
    auth_token: str,
    symbol: str,
    side: str,
    market: str,
    account_id: str,
    budget: float,
    leverage: Optional[int],
    grids: int,
    dry_run: bool,
) -> Dict[str, Any]:
    """שולח POST ל-/grid/trade בשרת הנוכחי."""
    import httpx
    payload: Dict[str, Any] = {
        "symbol": symbol,
        "side": side,
        "budget": float(budget),
        "grids": int(grids),
        "dry_run": bool(dry_run),
        "market": market,
        "account_id": account_id,
    }
    if market.lower().startswith("future"):
        payload["leverage"] = int(leverage or 1)

    headers = {}
    if auth_token:
        headers["Authorization"] = f"Bearer {auth_token}"
    headers["Content-Type"] = "application/json"

    async with httpx.AsyncClient(timeout=20.0) as cli:
        r = await cli.post(f"{base_url.rstrip('/')}/grid/trade", json=payload, headers=headers)
        try:
            data = r.json()
        except Exception:
            data = {"status_code": r.status_code, "text": r.text}
        data["_http_status"] = r.status_code
        return data


def _map_side_for_market(scan_side: str, market: str) -> str:
    """
    scan_side מגיע בדרך כלל BUY/SELL.
    נעשה מיפוי:
      - futures: BUY -> LONG, SELL -> SHORT
      - spot: נשאיר BUY/SELL
    """
    s = (scan_side or "").upper()
    if market.lower().startswith("future"):
        if s == "BUY":
            return OPS_DEFAULTS["side_fut_long"]
        if s == "SELL":
            return OPS_DEFAULTS["side_fut_short"]
        return OPS_DEFAULTS["side_fut_long"]
    # spot
    if s in ("BUY", "SELL"):
        return s
    return OPS_DEFAULTS["side_spot_buy"]


async def _telegram_notify(chat_id: Optional[str], text: str) -> None:
    """נשלח הודעת טלגרם קטנה אם ניתן (best-effort)."""
    if not chat_id:
        return
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not bot_token:
        return
    import httpx
    api = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "disable_web_page_preview": True}
    try:
        async with httpx.AsyncClient(timeout=10.0) as cli:
            await cli.post(api, json=payload)
    except Exception:
        pass


@router.get("/approve", summary="Approve trade from Telegram (public)")
async def ops_approve(
    request: Request,
    symbol: str = Query(...),
    side: str = Query(..., description="BUY/SELL from scan; will be mapped to LONG/SHORT for futures"),
    tf: Optional[str] = Query(None, description="Timeframe (meta)"),
    score: Optional[float] = Query(None),
    src: Optional[str] = Query(None, description="source tag, e.g., scan"),
    market: Optional[str] = Query(None, description="Override market, default from env"),
    account_id: Optional[str] = Query(None),
    budget: Optional[float] = Query(None),
    leverage: Optional[int] = Query(None),
    grids: Optional[int] = Query(None),
    dry_run: Optional[bool] = Query(None),
    chat_id: Optional[str] = Query(None, description="Optional chat to echo status"),
) -> Dict[str, Any]:
    base_url = os.getenv("PUBLIC_HOST", "").strip() or str(request.base_url).rstrip("/")
    mkt = (market or OPS_DEFAULTS["market"]).lower()
    acct = account_id or OPS_DEFAULTS["account_id"]
    budg = float(budget if budget is not None else OPS_DEFAULTS["budget"])
    lev = int(leverage if leverage is not None else OPS_DEFAULTS["leverage"])
    grd = int(grids if grids is not None else OPS_DEFAULTS["grids"])
    dry = bool(OPS_DEFAULTS["dry_run"] if dry_run is None else dry_run)

    eff_side = _map_side_for_market(side, mkt)

    # בצע בפועל:
    res = await _place_grid_trade(
        base_url=base_url,
        auth_token=INTERNAL_TOKEN,
        symbol=symbol.upper(),
        side=eff_side,
        market=mkt,
        account_id=acct,
        budget=budg,
        leverage=lev if mkt.startswith("future") else None,
        grids=grd,
        dry_run=dry,
    )
    ok = bool(res.get("ok", False)) and (200 <= int(res.get("_http_status", 0)) < 300)

    # החזר למשתמש + הודעה לטלגרם
    msg = (
        f"✅ APPROVED {symbol.upper()} {eff_side} (market={mkt}, budget={budg}, "
        f"grids={grd}{', lev='+str(lev) if mkt.startswith('future') else ''}, "
        f"dry_run={dry}) — {'OK' if ok else 'FAILED'}"
    )
    asyncio.create_task(_telegram_notify(chat_id, msg))

    return {
        "ok": ok,
        "action": "approve",
        "symbol": symbol.upper(),
        "side_effective": eff_side,
        "market": mkt,
        "account_id": acct,
        "budget": budg,
        "grids": grd,
        "leverage": lev if mkt.startswith("future") else None,
        "dry_run": dry,
        "tf": tf,
        "score": score,
        "src": src or "scan",
        "grid_trade_result": res,
        "note": "Triggered /grid/trade",
    }


@router.get("/reject", summary="Reject trade from Telegram (public)")
async def ops_reject(
    request: Request,
    symbol: str = Query(...),
    side: Optional[str] = Query(None),
    tf: Optional[str] = Query(None),
    score: Optional[float] = Query(None),
    src: Optional[str] = Query(None),
    chat_id: Optional[str] = Query(None),
) -> Dict[str, Any]:
    msg = f"⛔ REJECTED {symbol.upper()} {side or ''} (tf={tf}, score={score})"
    import asyncio
    asyncio.create_task(_telegram_notify(chat_id, msg))
    return {"ok": True, "action": "reject", "symbol": symbol.upper(), "side": side, "tf": tf, "score": score, "src": src or "scan"}
