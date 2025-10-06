# routes/locked_report.py
from __future__ import annotations
import os, time, json, hmac, hashlib
from typing import Any, Dict, List, Optional
from contextlib import suppress

import httpx
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse

router = APIRouter(tags=["ops-locked"])

PUBLIC_HOST      = (os.getenv("PUBLIC_HOST") or os.getenv("WEBHOOK_HOST") or "").strip()
API_BEARER_TOKEN = (os.getenv("API_BEARER_TOKEN") or os.getenv("API_TOKEN") or "").strip()
BOT_TOKEN        = (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
ADMIN_CHAT_ID    = os.getenv("TELEGRAM_CHAT_ID") or os.getenv("ADMIN_CHAT_ID")
HMAC_SECRET      = (os.getenv("WEBHOOK_HMAC_SECRET") or os.getenv("OPS_SIGN_SECRET") or "").strip()

def _sign_hex(secret_hex_or_text: str, payload: bytes) -> str:
    key = bytes.fromhex(secret_hex_or_text) if len(secret_hex_or_text)==64 else secret_hex_or_text.encode("utf-8")
    return hmac.new(key, payload, hashlib.sha256).hexdigest()

async def _send_tg(text: str, buttons: Optional[List[Dict[str,str]]] = None) -> Dict[str, Any]:
    if not BOT_TOKEN or not ADMIN_CHAT_ID:
        return {"ok": False, "skipped": True}
    payload: Dict[str, Any] = {
        "chat_id": int(ADMIN_CHAT_ID) if str(ADMIN_CHAT_ID).isdigit() else ADMIN_CHAT_ID,
        "text": text, "parse_mode": "HTML", "disable_web_page_preview": True,
    }
    if buttons:
        payload["reply_markup"] = {"inline_keyboard":[buttons]}
    async with httpx.AsyncClient(timeout=12.0) as cli:
        r = await cli.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage", json=payload)
        with suppress(Exception):
            return r.json()
        return {"ok": False, "status": r.status_code, "text": r.text}

def _calc_locked(entry: float, sl: float, qty: float, side: str) -> float:
    # USDT Perp assumption
    if side.upper() in ("LONG", "BUY"):
        return (sl - entry) * qty
    return (entry - sl) * qty

def _detect_position_side(qty: float) -> str:
    return "LONG" if qty > 0 else "SHORT"

def _get_positions_and_orders(symbols: List[str]) -> Dict[str, Any]:
    from binance.client import Client  # type: ignore
    api_key = os.getenv("BINANCE_API_KEY","").strip()
    api_sec = os.getenv("BINANCE_API_SECRET","").strip()
    if not api_key or not api_sec:
        raise HTTPException(status_code=500, detail="BINANCE keys missing")
    cli = Client(api_key, api_sec)
    out: Dict[str, Any] = {}
    for sym in symbols:
        symu = sym.upper().strip()
        entry, qty = 0.0, 0.0
        with suppress(Exception):
            pi = cli.futures_position_information(symbol=symu) or []
            if pi:
                entry = float(pi[0].get("entryPrice") or 0) or 0.0
                qty   = float(pi[0].get("positionAmt") or 0) or 0.0
        if abs(qty) < 1e-12:
            out[symu] = {"has_position": False}
            continue
        sl_price = None
        with suppress(Exception):
            orders = cli.futures_get_open_orders(symbol=symu) or []
            for o in orders:
                typ = str(o.get("type","")).upper()
                if "STOP" in typ:  # STOP / STOP_MARKET / STOP_LOSS_LIMIT
                    ro = str(o.get("reduceOnly","false")).lower() == "true"
                    if ro:
                        sp = float(o.get("stopPrice") or 0) or 0.0
                        if sp > 0:
                            sl_price = sp
                            break
        side = _detect_position_side(qty)
        out[symu] = {
            "has_position": True,
            "entryPrice": entry,
            "positionAmt": qty,
            "side": side,
            "sl_price": sl_price,
            "locked_pnl": _calc_locked(entry, sl_price, abs(qty), side) if (sl_price and entry) else None,
        }
    return out

@router.get("/ops/locked-pnl", summary="Locked PnL report for symbols (and optional Telegram message)")
async def locked_pnl(symbols: Optional[str] = Query(None, description="CSV symbols; default WATCHLIST"),
                     notify_tg: bool = Query(False, description="Send Telegram summary")):
    syms = [s.strip() for s in (symbols.split(",") if symbols else (os.getenv("WATCHLIST","") or "").split(",")) if s.strip()]
    if not syms:
        raise HTTPException(status_code=400, detail="no symbols")
    data = _get_positions_and_orders(syms)

    # Telegram summary
    if notify_tg and BOT_TOKEN and ADMIN_CHAT_ID and PUBLIC_HOST and HMAC_SECRET:
        lines: List[str] = ["💎 <b>Locked PnL</b> (est.)"]
        btn_rows: List[List[Dict[str,str]]] = []
        for sym, d in data.items():
            if not d.get("has_position"):
                lines.append(f"• {sym}: <code>no position</code>")
                continue
            lp = d.get("locked_pnl")
            slp = d.get("sl_price")
            lp_txt = f"{lp:.2f}" if isinstance(lp,(int,float)) else "—"
            sl_txt = f"{slp:.6g}" if slp else "—"
            lines.append(f"• {sym} {d.get('side','')} · SL=<code>{sl_txt}</code> · Locked=<code>{lp_txt}</code>")

            # Signed Tighten link
            payload = {"symbol": sym, "action": "tighten"}
            raw = json.dumps(payload, separators=(",",":")).encode("utf-8")
            sig = _sign_hex(HMAC_SECRET, raw)
            url = f"{PUBLIC_HOST.rstrip('/')}/ops/tighten/signed?payload={json.dumps(payload,separators=(',',':'))}&sig={sig}"
            btn_rows.append([{"text": f"🔒 Tighten {sym}", "url": url}])

        await _send_tg("\n".join(lines), buttons=None)
        # Send buttons separately to avoid long messages w/ many rows
        for row in btn_rows:
            await _send_tg("פעולה מהירה:", buttons=row)

    return JSONResponse({"ok": True, "data": data})

@router.get("/ops/tighten/signed", summary="Signed quick Tighten SL (GET) -> proxy to /position-ops/manage-once")
async def tighten_signed(payload: str = Query(...), sig: str = Query(...)):
    if not HMAC_SECRET:
        raise HTTPException(status_code=500, detail="HMAC secret not set")
    raw = payload.encode("utf-8")
    want = _sign_hex(HMAC_SECRET, raw)
    if not hmac.compare_digest(sig, want):
        raise HTTPException(status_code=401, detail="bad signature")

    try:
        obj = json.loads(payload)
        symbol = str(obj.get("symbol") or "").upper()
        if not symbol:
            raise ValueError("symbol missing")
    except Exception:
        raise HTTPException(status_code=400, detail="bad payload")

    base = PUBLIC_HOST.rstrip("/")
    token = API_BEARER_TOKEN
    if not base or not token:
        raise HTTPException(status_code=500, detail="missing base or token")

    # The downstream route should interpret tighten=True, or action="tighten"
    body = {"symbol": symbol, "tighten": True, "action": "tighten"}
    async with httpx.AsyncClient(timeout=15.0) as cli:
        r = await cli.post(f"{base}/position-ops/manage-once",
                           headers={"Authorization": f"Bearer {token}"},
                           json=body)
    if r.status_code >= 300:
        raise HTTPException(status_code=r.status_code, detail=r.text)
    return {"ok": True, "symbol": symbol, "forward_status": r.status_code}
