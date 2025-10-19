# routes/public_trade_status.py
# -*- coding: utf-8 -*-
from __future__ import annotations
import os, json, time
from typing import Optional, Dict, Any
from contextlib import suppress

from fastapi import APIRouter, Query, Response, Request, HTTPException
from fastapi.responses import PlainTextResponse, JSONResponse

router = APIRouter(prefix="/public/trade", tags=["Public Trade"])

# איפה לשמור/לקרוא ברירת־מחדל אם אין Snapshot Store:
OPEN_TRADE_STATUS_PATH = os.getenv(
    "OPEN_TRADE_STATUS_PATH",
    "/app/static/cache/open_trade_status.json"
)

# נסה לייבא Snapshot Store (אם הוספת את המודולים שלי)
_snapshot_get = None
with suppress(Exception):
    from utils.snapshot_store import get_snapshot as _snapshot_get  # type: ignore

def _read_default_snapshot() -> Dict[str, Any]:
    try:
        if os.path.exists(OPEN_TRADE_STATUS_PATH):
            with open(OPEN_TRADE_STATUS_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return {}

def _dir(side: str | None) -> int:
    s = (side or "").upper()
    if s in ("BUY","LONG"):
        return +1
    if s in ("SELL","SHORT"):
        return -1
    return 0

def _fmt_pct(x: float, dp: int = 2) -> str:
    s = f"{x:.{dp}f}%"
    if x > 0:
        s = "+" + s
    return s

def _fmt_px(x: Optional[float]) -> str:
    if x is None:
        return "—"
    try:
        xv = float(x)
    except Exception:
        return "—"
    if xv >= 1000:
        # קיצור אלגנטי לאלפים, בלי פסיקים ל־Telegram
        return f"{int(round(xv, 0))}"
    out = f"{xv:.3f}".rstrip("0").rstrip(".")
    return out or "0"

def _now_local(ts: Optional[float] = None, tz_offset_hours: int = 3) -> str:
    t = time.time() if ts is None else ts
    # תצוגה בלבד (GMT+3 כפי שביקשת בלוגים)
    return time.strftime("%H:%M", time.gmtime(t + tz_offset_hours * 3600))

def _prob_str(p: Optional[Dict[str, float]]) -> str:
    if not p or not isinstance(p, dict):
        return "—"
    tp1 = p.get("tp1")
    tp2 = p.get("tp2")
    tp3 = p.get("tp3")
    if all(v is not None for v in (tp1, tp2, tp3)):
        try:
            return f"{int(round(float(tp1)*100))}/{int(round(float(tp2)*100))}/{int(round(float(tp3)*100))}"
        except Exception:
            return "—"
    return "—"

def _eta_str(eta: Optional[Dict[str, Any]]) -> str:
    if not eta or not isinstance(eta, dict):
        return "—"
    t1 = eta.get("tp1_sec")
    try:
        if isinstance(t1, (int, float)) and t1 >= 0:
            m = int(round(float(t1) / 60.0))
            return f"~{m}m"
    except Exception:
        pass
    return "—"

def _compute_pnl_pct(side: Optional[str], entry: Optional[float], last: Optional[float],
                     pnl_override: Optional[float]) -> float:
    """
    עדיפות:
    1) אם קיים pnl_override (מ־query/snapshot) – נשתמש בו (אחוזים).
    2) אחרת מחשבים ((last - entry) * dir / entry) * 100 אם ניתן.
    """
    if pnl_override is not None:
        try:
            return float(pnl_override)
        except Exception:
            pass
    d = _dir(side)
    try:
        if d != 0 and entry and last and entry != 0:
            return ((float(last) - float(entry)) * d / float(entry)) * 100.0
    except Exception:
        pass
    return 0.0

def _compose_line(
    symbol: str,
    side: str,
    qty: Optional[float],
    entry: Optional[float],
    last: Optional[float],
    sl: Optional[float],
    tp1: Optional[float],
    tp2: Optional[float],
    tp3: Optional[float],
    lo: Optional[float],
    hi: Optional[float],
    probs: Optional[Dict[str, float]],
    eta: Optional[Dict[str, Any]],
    pnl_pct: float,
    tz_label: str = "GMT+3",
) -> str:
    side_txt = "long" if _dir(side) > 0 else ("short" if _dir(side) < 0 else "—")
    parts = [
        f"{(symbol or '—').upper()} {side_txt}",
        f"כניסה { _fmt_px(entry) }",
        f"עכשיו { _fmt_px(last) }",
        f"PnL {_fmt_pct(pnl_pct)}",
    ]

    # טווח יומי/נוכחי אם קיים
    if lo or hi:
        parts.append(f"טווח { _fmt_px(lo) }–{ _fmt_px(hi) }")

    # SL/TPs
    if sl:
        parts.append(f"SL {_fmt_px(sl)}")
    tps = [v for v in (tp1, tp2, tp3) if v]
    if tps:
        parts.append("TP " + "/".join(_fmt_px(v) for v in tps))

    # ETA+Prob
    if eta:
        parts.append(f"ETA { _eta_str(eta) }")
    if probs:
        parts.append(f"prob { _prob_str(probs) }")

    parts.append(f"{tz_label} {_now_local()}")

    # דחיסה לשורה אחת
    line = " | ".join(parts)
    if len(line) > 220:
        line = line[:217] + "..."
    return line

async def _load_snapshot(symbol_hint: Optional[str]) -> Dict[str, Any]:
    """
    ניסיון טעינה לפי סדר:
    1) אם קיים Snapshot Store ובא query param 'symbol' → קח אותו.
    2) אם אין/לא נמצא → קובץ קאש דיפולטי.
    """
    if _snapshot_get and symbol_hint:
        with suppress(Exception):
            snap = await _snapshot_get(symbol_hint)
            if snap:
                return snap
    # fallback file
    return _read_default_snapshot()

@router.get(
    "/status",
    summary="Short mixed he/en open-trade status line",
    response_class=PlainTextResponse
)
async def public_trade_status(
    request: Request,
    # אפשר להביא הכל דרך פרמטרים (לטלגרם webhook יבש),
    # או להשאיר ריקים ונקרא מ־snapshot/file:
    symbol: Optional[str] = Query(default=None),
    side: Optional[str] = Query(default=None),
    qty: Optional[float] = Query(default=None),
    entry: Optional[float] = Query(default=None, description="Entry price"),
    last: Optional[float]  = Query(default=None, description="Last/Now price"),
    sl: Optional[float]    = Query(default=None),
    tp1: Optional[float]   = Query(default=None),
    tp2: Optional[float]   = Query(default=None),
    tp3: Optional[float]   = Query(default=None),
    low: Optional[float]   = Query(default=None),
    high: Optional[float]  = Query(default=None),
    pnl: Optional[float]   = Query(default=None, description="PnL percent override (e.g., 1.25 for +1.25%)"),
    fmt: str               = Query(default="text", pattern="^(text|json)$"),
    tz: str                = Query(default="GMT+3"),
) -> Response:
    data: Dict[str, Any] = {}

    # 1) אם סופקו symbol+side בפרמטרים – נעדיף אותם
    if symbol and side:
        data = {
            "symbol": symbol, "side": side, "qty": qty,
            "entry": entry, "last": last,
            "sl": sl, "tp1": tp1, "tp2": tp2, "tp3": tp3,
            "low": low, "high": high,
            "pnl": pnl,
        }
    else:
        # 2) אחרת – נטען snapshot (מ־store אם קיים, אחרת מקובץ)
        snap = await _load_snapshot(symbol_hint=symbol)
        if not snap:
            # אין מידע בכלל
            empty_line = _compose_line(
                symbol=(symbol or "—"),
                side=(side or "—"),
                qty=None, entry=None, last=None, sl=None,
                tp1=None, tp2=None, tp3=None,
                lo=None, hi=None,
                probs=None, eta=None,
                pnl_pct=0.0,
                tz_label=tz,
            )
            want_json = (fmt == "json") or ("application/json" in (request.headers.get("accept") or ""))
            if want_json:
                return JSONResponse({"ok": True, "line": empty_line, "ts": int(time.time())})
            return PlainTextResponse(empty_line)

        # תמיכה גם במבנים עשירים (plan/result) וגם שטוח:
        data = {
            "symbol": snap.get("symbol") or snap.get("plan", {}).get("symbol"),
            "side":   snap.get("side")   or snap.get("plan", {}).get("side"),
            "qty":    snap.get("qty")    or snap.get("quantity") or snap.get("plan", {}).get("qty"),
            "entry":  snap.get("entry")  or snap.get("entry_price") or snap.get("price_ref") or snap.get("plan", {}).get("entry_price"),
            "last":   snap.get("last")   or snap.get("now") or snap.get("price") or snap.get("ticker", {}).get("price"),
            "sl":     (snap.get("sl_price")
                       or (snap.get("sl") or {}).get("stopPrice")
                       or snap.get("plan", {}).get("sl_price")),
            "low":    snap.get("low"),
            "high":   snap.get("high"),
            "pnl":    snap.get("pnl"),  # אם קיים – נשמר כ־override
        }

        # תדלוף TP-ים אם קיימים בצורת רשימה/legs
        legs = (snap.get("tp") or snap.get("tp_legs") or [])
        if isinstance(legs, list) and legs:
            for i in range(min(3, len(legs))):
                leg = legs[i] or {}
                px = leg.get("stopPrice") or leg.get("price") or leg.get("tp_price")
                if   i == 0: data["tp1"] = px
                elif i == 1: data["tp2"] = px
                elif i == 2: data["tp3"] = px

        # הסתברות/ETA אם יש
        data["_probs"] = snap.get("probs") or snap.get("plan", {}).get("probs")
        data["_eta"]   = snap.get("eta")   or snap.get("plan", {}).get("eta")

    # הגנות ונירמול
    symbol = (data.get("symbol") or "")[:24]
    side   = (data.get("side") or "")
    qty    = data.get("qty")
    # מספרים
    def _f(x: Any) -> Optional[float]:
        try:
            return float(x)
        except Exception:
            return None

    entry  = _f(data.get("entry"))
    last   = _f(data.get("last"))
    sl     = _f(data.get("sl"))
    tp1    = _f(data.get("tp1"))
    tp2    = _f(data.get("tp2"))
    tp3    = _f(data.get("tp3"))
    low    = _f(data.get("low"))
    high   = _f(data.get("high"))
    pnl_in = _f(data.get("pnl")) if (data.get("pnl") is not None) else _f(pnl)

    probs  = data.get("_probs") if isinstance(data.get("_probs"), dict) else None
    eta    = data.get("_eta")   if isinstance(data.get("_eta"), dict)   else None

    # חישוב PnL אחוזי (עם override אם קיים)
    pnl_pct = _compute_pnl_pct(side=side, entry=entry, last=last, pnl_override=pnl_in)

    # בנה שורת סטטוס:
    line = _compose_line(
        symbol=symbol or "—",
        side=side or "—",
        qty=qty, entry=entry, last=last, sl=sl,
        tp1=tp1, tp2=tp2, tp3=tp3,
        lo=low, hi=high,
        probs=probs, eta=eta,
        pnl_pct=pnl_pct,
        tz_label=tz
    )

    # החזר בפורמט המבוקש
    want_json = (fmt == "json") or ("application/json" in (request.headers.get("accept") or ""))
    if want_json:
        payload = {
            "ok": True,
            "symbol": symbol or None,
            "side": side or None,
            "qty": qty,
            "entry": entry,
            "last": last,
            "sl": sl,
            "tp": [v for v in (tp1, tp2, tp3) if v is not None],
            "range": {"low": low, "high": high} if (low is not None or high is not None) else None,
            "eta": eta,
            "probs": probs,
            "pnl": pnl_pct,             # מספרי (אחוזים)
            "pnl_str": _fmt_pct(pnl_pct),
            "line": line,
            "tz": tz,
            "ts": int(time.time()),
        }
        return JSONResponse(payload)

    return PlainTextResponse(line)
