# routes/public_trade_status.py
# -*- coding: utf-8 -*-
from __future__ import annotations
import os, math, json, time
from typing import Optional, Dict, Any

from fastapi import APIRouter, Query, Response, Request
from fastapi.responses import PlainTextResponse, JSONResponse

router = APIRouter(prefix="/public/trade", tags=["Public Trade"])

# מאיפה להביא ברירת־מחדל של סטטוס אם לא הועברו פרמטרים:
# ניתן לכתוב את הקובץ הזה ע״י המערכת שלך בכל עדכון:
OPEN_TRADE_STATUS_PATH = os.getenv(
    "OPEN_TRADE_STATUS_PATH",
    "/app/static/cache/open_trade_status.json"
)

def _read_default_snapshot() -> Dict[str, Any]:
    try:
        with open(OPEN_TRADE_STATUS_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def _dir(side: str) -> int:
    s = (side or "").upper()
    if s in ("BUY","LONG"): return +1
    if s in ("SELL","SHORT"): return -1
    return 0

def _fmt_pct(x: float, dp: int = 2) -> str:
    s = f"{x:.{dp}f}%"
    if x > 0: s = "+" + s
    return s

def _fmt_px(x: Optional[float]) -> str:
    if x is None: return "—"
    if x >= 1000:
        # קיצור אלגנטי אלפים
        return f"{int(round(x, 0)):,}".replace(",", "")
    return f"{x:.3f}".rstrip("0").rstrip(".")

def _now_local(ts: Optional[float] = None, tz_offset_hours: int = 3) -> str:
    t = time.time() if ts is None else ts
    # הצגה בלבד (GMT+3 כפי שביקשת בלוגים)
    return time.strftime("%H:%M", time.gmtime(t + tz_offset_hours*3600))

def _prob_str(p: Optional[Dict[str, float]]) -> str:
    if not p: return "—"
    # תומך גם בשמות tp1/tp2/tp3 וגם במערך:
    tp1 = p.get("tp1") if isinstance(p, dict) else None
    tp2 = p.get("tp2") if isinstance(p, dict) else None
    tp3 = p.get("tp3") if isinstance(p, dict) else None
    if all(v is not None for v in (tp1, tp2, tp3)):
        return f"{int(round(tp1*100))}/{int(round(tp2*100))}/{int(round(tp3*100))}"
    return "—"

def _eta_str(eta: Optional[Dict[str, Any]]) -> str:
    if not eta: return "—"
    # מצפה לשדות שניות: tp1_sec/tp2_sec/tp3_sec
    t1 = eta.get("tp1_sec")
    if isinstance(t1, (int, float)) and t1 >= 0:
        # המרה לדקות בקירוב
        m = int(round(t1/60))
        return f"~{m}m"
    return "—"

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
    tz: str = "GMT+3",
) -> str:
    d = _dir(side)
    pnl_pct = 0.0
    if (entry or 0) and (last or 0) and d != 0:
        pnl_pct = ( (last - entry) * d / entry ) * 100.0

    side_txt = "long" if d > 0 else ("short" if d < 0 else "—")
    # he/en mix, קצר וקולע
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
    if sl:  parts.append(f"SL {_fmt_px(sl)}")
    tps = [v for v in (tp1, tp2, tp3) if v]
    if tps:
        parts.append("TP " + "/".join(_fmt_px(v) for v in tps))

    # ETA+Prob
    if eta:   parts.append(f"ETA { _eta_str(eta) }")
    if probs: parts.append(f"prob { _prob_str(probs) }")

    parts.append(f"{tz} {_now_local()}")

    # דחיסה לשורה אחת
    line = " | ".join(parts)
    # קיצור אם יצא ארוך מאוד
    if len(line) > 220:
        line = line[:217] + "..."
    return line

@router.get("/status", summary="Short mixed he/en open-trade status line",
            response_class=PlainTextResponse)
async def public_trade_status(
    request: Request,
    # אפשר להביא הכל דרך פרמטרים (לטלגרם webhook יבש), או להשאיר ריק ונקרא מ־JSON בקובץ:
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
    fmt: str               = Query(default="text", pattern="^(text|json)$"),
    tz: str                = Query(default="GMT+3"),
) -> Response:
    data: Dict[str, Any] = {}

    # 1) אסוף מהפרמטרים אם נמסרו
    if symbol and side:
        data = {
            "symbol": symbol, "side": side, "qty": qty,
            "entry": entry, "last": last,
            "sl": sl, "tp1": tp1, "tp2": tp2, "tp3": tp3,
            "low": low, "high": high,
        }
    else:
        # 2) אחרת נסה קריאה מ־snapshot (המערכת יכולה לעדכן אותו כל כמה שניות)
        snap = _read_default_snapshot() or {}
        # נתמך: גם מבנים עשירים (plan/result) וגם שטוח:
        data = {
            "symbol": snap.get("symbol") or snap.get("plan", {}).get("symbol"),
            "side": snap.get("side") or snap.get("plan", {}).get("side"),
            "qty": snap.get("qty") or snap.get("quantity") or snap.get("plan", {}).get("qty"),
            "entry": snap.get("entry_price") or snap.get("price_ref") or snap.get("plan", {}).get("entry_price"),
            "last": snap.get("last") or snap.get("now") or snap.get("price") or snap.get("ticker", {}).get("price"),
            "sl": (snap.get("sl_price")
                   or (snap.get("sl") or {}).get("stopPrice")
                   or snap.get("plan", {}).get("sl_price")),
            "tp1": None, "tp2": None, "tp3": None,
            "low": snap.get("low"), "high": snap.get("high"),
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
        data["_eta"]   = snap.get("eta") or snap.get("plan", {}).get("eta")

    # הגנות
    symbol = (data.get("symbol") or "")[:24]
    side   = (data.get("side") or "")
    qty    = data.get("qty")
    entry  = float(data.get("entry") or 0.0) or None
    last   = float(data.get("last") or 0.0) or None
    sl     = float(data.get("sl") or 0.0) or None
    tp1    = float(data.get("tp1") or 0.0) or None
    tp2    = float(data.get("tp2") or 0.0) or None
    tp3    = float(data.get("tp3") or 0.0) or None
    low    = float(data.get("low") or 0.0) or None
    high   = float(data.get("high") or 0.0) or None
    probs  = data.get("_probs") if isinstance(data.get("_probs"), dict) else None
    eta    = data.get("_eta")   if isinstance(data.get("_eta"), dict)   else None

    # בנה שורת סטטוס:
    line = _compose_line(
        symbol=symbol or "—",
        side=side or "—",
        qty=qty, entry=entry, last=last, sl=sl,
        tp1=tp1, tp2=tp2, tp3=tp3,
        lo=low, hi=high,
        probs=probs, eta=eta,
        tz=tz
    )

    # השב בפורמט המבוקש
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
            "tp": [v for v in (tp1, tp2, tp3) if v],
            "range": {"low": low, "high": high} if (low or high) else None,
            "eta": eta,
            "probs": probs,
            "line": line,
            "tz": tz,
            "ts": int(time.time())
        }
        return JSONResponse(payload)
    return PlainTextResponse(line)
