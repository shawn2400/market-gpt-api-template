# workers/watchdog.py
from __future__ import annotations
import os, time, json, asyncio, logging, math
from typing import Dict, Any, List, Optional
from zoneinfo import ZoneInfo
from datetime import datetime

import httpx

from utils.hmac_utils import build_signed_outbound, generate_idempotency_key
from utils.redis_client import redis_client as RED

LOGGER = logging.getLogger("watchdog")
logging.basicConfig(level=os.getenv("LOG_LEVEL","INFO").upper())

# ---- Config ----
FUTURES_BASE = os.getenv("BINANCE_FUTURES_HTTP_BASE","https://fapi.binance.com")

ACTIVE_URL   = os.getenv("ALERTS_ACTIVE_URL","http://127.0.0.1:8000/alerts/trades/active")
UPDATE_URL   = os.getenv("ALERTS_UPDATE_URL","http://127.0.0.1:8000/alerts/trades/update")
ANALYSIS_URL = os.getenv("ALERTS_ANALYSIS_URL","http://127.0.0.1:8000/alerts/analysis")
CONTEXT_URL  = os.getenv("CONTEXT_URL","http://127.0.0.1:8000")  # לשערוך vol/chop בשקט

WEBHOOK_HMAC_SECRET = os.getenv("WEBHOOK_HMAC_SECRET","").strip()

INTERVAL_SEC  = int(float(os.getenv("WATCHDOG_INTERVAL_SEC","20")))
BASE_NEAR_PCT = float(os.getenv("WATCHDOG_NEAR_PCT","0.25"))  # בסיס “כמעט”
SL_BE_ON_TP1  = os.getenv("SL_BE_ON_TP1","1").lower() in ("1","true","yes")

TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", os.getenv("ADMIN_CHAT_ID","")).strip()

# Digest יומי
DIGEST_TZ     = os.getenv("DIGEST_TZ","Asia/Jerusalem")
DIGEST_HOUR   = int(os.getenv("DIGEST_HOUR","9"))
DIGEST_MINUTE = int(os.getenv("DIGEST_MINUTE","0"))
DIGEST_ENABLED= os.getenv("DIGEST_ENABLED","1").lower() in ("1","true","yes")

# Quiet gating (דל-עומס)
NEAR_PCT_HIGHVOL = float(os.getenv("NEAR_PCT_HIGHVOL","0.15"))  # סף צר יותר ב-High Vol
NEAR_PCT_CHOP    = float(os.getenv("NEAR_PCT_CHOP","0.10"))     # סף עוד יותר צר ב-Chop
SUPPRESS_CHOP_NEAR= os.getenv("SUPPRESS_CHOP_NEAR","1").lower() in ("1","true","yes")

# ---- HTTP helpers ----
async def _get_active() -> List[Dict[str, Any]]:
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(ACTIVE_URL)
        r.raise_for_status()
        return r.json().get("items",[])

async def _get_prices(symbols: List[str]) -> Dict[str, float]:
    if not symbols:
        return {}
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(f"{FUTURES_BASE}/fapi/v1/ticker/price")
        r.raise_for_status()
        arr = r.json()
    out = {}
    want = set(s.upper() for s in symbols)
    for it in arr:
        s = it.get("symbol")
        if s in want:
            try:
                out[s] = float(it.get("price"))
            except Exception:
                pass
    return out

async def _get_context(symbols: List[str], interval: str = "15m") -> Dict[str, Any]:
    """
    מחזיר מפה symbol->flags (vol_regime,danger_chop, trending_*)
    דל-עומס: קריאה אחת לכל הסבב, או לא בכלל אם CONTEXT_URL לא מוגדר.
    """
    if not CONTEXT_URL:
        return {}
    payload = {"symbols": symbols, "interval": interval, "compact": True}
    async with httpx.AsyncClient(timeout=12) as client:
        try:
            r = await client.post(CONTEXT_URL.rstrip("/") + "/context/batch", json=payload)
            r.raise_for_status()
            items = r.json().get("items", [])
            return {it["symbol"]: (it.get("filters") or {}) for it in items}
        except Exception:
            return {}

async def _update_trade(tid: str, updates: Dict[str, Any]):
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.post(UPDATE_URL, json={"trade_id": tid, "updates": updates})
        r.raise_for_status()
        return r.json()

async def _notify(text: str, chat_id: str|int|None, reply_to: int|None = None, silent: bool = True, reply_markup: Optional[dict]=None):
    if not WEBHOOK_HMAC_SECRET or not chat_id:
        return
    payload = {"chat_id": chat_id, "text": text, "reply_to_message_id": reply_to, "silent": silent, "reply_markup": reply_markup}
    body, headers = build_signed_outbound(
        WEBHOOK_HMAC_SECRET, payload,
        idempotency_key=generate_idempotency_key(),
        extra_headers={"Content-Type":"application/json"},
    )
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.post(ANALYSIS_URL, content=body, headers=headers)
        r.raise_for_status()

def _pct(a: float, b: float) -> float:
    try: return abs(a-b)/b*100.0 if b else 0.0
    except Exception: return 0.0

def _f(x):
    try: 
        v = float(x)
        return v if v==v else None
    except Exception:
        return None

def _parse_json_field(val, default):
    if isinstance(val, dict): return val
    if isinstance(val, str):
        try: return json.loads(val)
        except Exception: return default
    return default

def _dynamic_near_pct(base: float, flags: Dict[str, Any]) -> float:
    """
    Quiet gating:
      - אם High Vol → סף near יותר קטן
      - אם Chop → קטן יותר/מדוכא לגמרי לפי SUPPRESS_CHOP_NEAR
    """
    vol = (flags or {}).get("vol_regime","mid")
    chop = bool((flags or {}).get("danger_chop", False))
    if chop and SUPPRESS_CHOP_NEAR:
        return 0.0  # לא נשגר near בכלל
    if vol == "high":
        return min(base, NEAR_PCT_HIGHVOL)
    if chop:
        return min(base, NEAR_PCT_CHOP)
    return base

def _tp_scale_hint(rec: Dict[str, Any]) -> Optional[List[float]]:
    """
    מחזיר [p1,p2,p3] אם קיים בקלט
    """
    scale = rec.get("tp_scale")
    if scale is None:
        return None
    try:
        if isinstance(scale, str):
            v = json.loads(scale)
        else:
            v = scale
        if isinstance(v, list) and len(v) == 3:
            return [float(v[0]), float(v[1]), float(v[2])]
    except Exception:
        pass
    return None

# ---- Digest state ----
def _digest_key(date_str: str) -> str:
    return f"algogpt:digest:{date_str}"

def _seen_digest_today(date_str: str) -> bool:
    if RED:
        return bool(RED.get(_digest_key(date_str)))
    # In-memory fallback (סטייט יעבוד רק כל עוד התהליך חי)
    return hasattr(_seen_digest_today, "_d") and getattr(_seen_digest_today, "_d") == date_str

def _mark_digest_sent(date_str: str):
    if RED:
        RED.setex(_digest_key(date_str), 36*3600, "1")
    else:
        setattr(_seen_digest_today, "_d", date_str)

async def _send_daily_digest(active: List[Dict[str, Any]]):
    if not DIGEST_ENABLED or not active:
        return
    try:
        tz = ZoneInfo(DIGEST_TZ)
    except Exception:
        tz = None
    now = datetime.now(tz) if tz else datetime.now()
    date_str = now.strftime("%Y-%m-%d")
    if now.hour != DIGEST_HOUR or now.minute < DIGEST_MINUTE or _seen_digest_today(date_str):
        return
    # בונים מסר דחוס
    lines = [f"🗞️ *Daily Digest* — {date_str}"]
    for it in active[:30]:  # תקרה תצוגתית
        sym = it.get("symbol","")
        side = it.get("side","")
        entry = _f(it.get("entry")); sl = _f(it.get("sl"))
        tp1 = _f(it.get("tp1")); tp2 = _f(it.get("tp2")); tp3 = _f(it.get("tp3"))
        nowp = _f(it.get("current_price"))
        # מרחקים גסים
        d1 = f"{_pct(nowp,tp1):.2f}%" if nowp and tp1 else "—"
        ds = f"{_pct(nowp,sl):.2f}%" if nowp and sl else "—"
        lines.append(f"- {sym} {side}: Now `{nowp or '—'}` | TP1 {d1} | SL {ds}")
    text = "\n".join(lines)
    await _notify(text, TELEGRAM_CHAT_ID, reply_to=None, silent=True)
    _mark_digest_sent(date_str)

# ---- Main step ----
async def step():
    items = await _get_active()
    if not items:
        return

    symbols = [it.get("symbol","") for it in items if it.get("symbol")]
    prices = await _get_prices(symbols)
    # flags לשקט/תנודתיות
    flags_map = await _get_context(symbols, "15m")  # דל-עומס: בקשה אחת לסבב

    for it in items:
        tid = str(it.get("trade_id"))
        sym = it.get("symbol","")
        ttype = (it.get("trade_type") or "FUTURES").upper()
        chat_id = it.get("chat_id") or TELEGRAM_CHAT_ID
        price = prices.get(sym)
        if not price:
            continue

        hits = _parse_json_field(it.get("hits"), {"tp1":False,"tp2":False,"tp3":False,"sl":False})
        near = _parse_json_field(it.get("near"), {"tp1":False,"tp2":False,"tp3":False,"sl":False})
        flags = flags_map.get(sym, {})

        # TP scale (אם קיים) – תזכורות טקסטואליות
        scale = _tp_scale_hint(it)  # [p1,p2,p3] או None

        # ב-FUTURES/SPOT מבצעים ניטור סטנדרטי
        if ttype in ("FUTURES","SPOT"):
            side = (it.get("side") or "LONG").upper()
            entry = _f(it.get("entry"))
            sl = _f(it.get("sl"))
            tp1 = _f(it.get("tp1")); tp2 = _f(it.get("tp2")); tp3 = _f(it.get("tp3"))

            # near alerts עם quiet gating
            near_pct = _dynamic_near_pct(BASE_NEAR_PCT, flags)
            if near_pct > 0.0:
                if tp1 and not near.get("tp1") and _pct(price, tp1) <= near_pct:
                    near["tp1"] = True
                    await _notify(f"⏳ {sym} כמעט TP1 ({price:.6f} ~ {tp1:.6f})", chat_id, silent=True)
                if tp2 and not near.get("tp2") and _pct(price, tp2) <= near_pct:
                    near["tp2"] = True
                    await _notify(f"⏳ {sym} כמעט TP2 ({price:.6f} ~ {tp2:.6f})", chat_id, silent=True)
                if tp3 and not near.get("tp3") and _pct(price, tp3) <= near_pct:
                    near["tp3"] = True
                    await _notify(f"⏳ {sym} כמעט TP3 ({price:.6f} ~ {tp3:.6f})", chat_id, silent=True)
                if sl and not near.get("sl") and _pct(price, sl) <= near_pct:
                    near["sl"] = True
                    await _notify(f"⚠️ {sym} קרוב ל-SL ({price:.6f} ~ {sl:.6f})", chat_id, silent=True)

            # TP1 hit → SL→BE + כפתורי ניהול
            if tp1 and not hits.get("tp1"):
                crossed = (price >= tp1) if side == "LONG" else (price <= tp1)
                if crossed:
                    hits["tp1"] = True
                    updates = {"hits": json.dumps(hits), "near": json.dumps(near)}
                    kb = {"inline_keyboard":[
                        [{"text":"🔒 SL→BE","callback_data":f"slbe:{tid}"}],
                        [{"text":"📊 TP Scale","callback_data":f"tpask:{tid}"}],
                    ]}
                    await _notify(f"✅ {sym} TP1 — רוצה לקבע SL ל-BE?", chat_id, reply_to=it.get("message_id"), silent=False, reply_markup=kb)

                    # תזכורת טקסטואלית לפי scale אם קיים
                    if scale:
                        await _notify(f"ℹ️ הצעה: סגור ~{int(scale[0])}% ב-TP1", chat_id, reply_to=it.get("message_id"), silent=True)

                    if SL_BE_ON_TP1 and entry:
                        updates["sl"] = float(entry)
                        await _notify(f"🔒 SL הוזז ל-BE ({entry:.6f})", chat_id, reply_to=it.get("message_id"), silent=False)
                    await _update_trade(tid, updates)
                    continue

            # TP2 hit
            if tp2 and not hits.get("tp2"):
                crossed = (price >= tp2) if side == "LONG" else (price <= tp2)
                if crossed:
                    hits["tp2"] = True
                    await _notify(f"✅ {sym} TP2", chat_id, reply_to=it.get("message_id"), silent=False)
                    if scale:
                        await _notify(f"ℹ️ הצעה: סגור ~{int(scale[1])}% ב-TP2", chat_id, reply_to=it.get("message_id"), silent=True)
                    await _update_trade(tid, {"hits": json.dumps(hits), "near": json.dumps(near)})
                    continue

            # TP3 hit
            if tp3 and not hits.get("tp3"):
                crossed = (price >= tp3) if side == "LONG" else (price <= tp3)
                if crossed:
                    hits["tp3"] = True
                    await _notify(f"✅ {sym} TP3 — סגירה מלאה/חלקית לפי נוהל", chat_id, reply_to=it.get("message_id"), silent=False)
                    if scale:
                        await _notify(f"ℹ️ הצעה: סגור ~{int(scale[2])}% ב-TP3", chat_id, reply_to=it.get("message_id"), silent=True)
                    await _update_trade(tid, {"hits": json.dumps(hits), "near": json.dumps(near)})
                    continue

            # SL hit
            if sl and not hits.get("sl"):
                crossed = (price <= sl) if side == "LONG" else (price >= sl)
                if crossed:
                    hits["sl"] = True
                    await _notify(f"🛑 {sym} SL הופעל", chat_id, reply_to=it.get("message_id"), silent=False)
                    await _update_trade(tid, {"hits": json.dumps(hits), "near": json.dumps(near)})
                    continue

        elif ttype == "GRID":
            # אפשר להרחיב בעתיד: התראות על מגע בקווי גריד
            pass

    # Digest יומי (בתום מעבר על כל הטריידים)
    await _send_daily_digest(items)

# ---- Loop ----
async def main():
    while True:
        try:
            await step()
            await asyncio.sleep(INTERVAL_SEC)
        except Exception as e:
            LOGGER.exception("watchdog error: %s", e)
            await asyncio.sleep(5)

if __name__ == "__main__":
    asyncio.run(main())
