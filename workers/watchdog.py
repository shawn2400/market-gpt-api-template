# workers/watchdog.py
from __future__ import annotations
import os, time, json, asyncio, logging
from typing import Dict, Any, List, Optional
from zoneinfo import ZoneInfo
from datetime import datetime
import httpx

from utils.hmac_utils import build_signed_outbound, generate_idempotency_key
from utils.redis_client import redis_client as RED
from utils.runtime_prefs import (
    is_muted, mute_remaining_sec,
    get_near_pct_override,
    is_grid_alerts_enabled,
    is_trade_quiet,
)

LOGGER = logging.getLogger("watchdog")
logging.basicConfig(level=os.getenv("LOG_LEVEL","INFO").upper())

# ---- Config ----
FUTURES_BASE = os.getenv("BINANCE_FUTURES_HTTP_BASE","https://fapi.binance.com")

ACTIVE_URL   = os.getenv("ALERTS_ACTIVE_URL","http://127.0.0.1:8000/alerts/trades/active")
UPDATE_URL   = os.getenv("ALERTS_UPDATE_URL","http://127.0.0.1:8000/alerts/trades/update")
ANALYSIS_URL = os.getenv("ALERTS_ANALYSIS_URL","http://127.0.0.1:8000/alerts/analysis")
CONTEXT_URL  = os.getenv("CONTEXT_URL","http://127.0.0.1:8000")

WEBHOOK_HMAC_SECRET = os.getenv("WEBHOOK_HMAC_SECRET","").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", os.getenv("ADMIN_CHAT_ID","")).strip()

INTERVAL_SEC  = int(float(os.getenv("WATCHDOG_INTERVAL_SEC","20")))
BASE_NEAR_PCT = float(os.getenv("WATCHDOG_NEAR_PCT","0.25"))
SL_BE_ON_TP1  = os.getenv("SL_BE_ON_TP1","1").lower() in ("1","true","yes")

# Daily digest
DIGEST_TZ     = os.getenv("DIGEST_TZ","Asia/Jerusalem")
DIGEST_HOUR   = int(os.getenv("DIGEST_HOUR","9"))
DIGEST_MINUTE = int(os.getenv("DIGEST_MINUTE","0"))
DIGEST_ENABLED= os.getenv("DIGEST_ENABLED","1").lower() in ("1","true","yes")

# Quiet gating for near alerts
NEAR_PCT_HIGHVOL = float(os.getenv("NEAR_PCT_HIGHVOL","0.15"))
NEAR_PCT_CHOP    = float(os.getenv("NEAR_PCT_CHOP","0.10"))
SUPPRESS_CHOP_NEAR= os.getenv("SUPPRESS_CHOP_NEAR","1").lower() in ("1","true","yes")

# ---- HTTP helpers ----
async def _get_active() -> List[Dict[str, Any]]:
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(ACTIVE_URL)
        r.raise_for_status()
        return r.json().get("items",[])

async def _get_prices(symbols: List[str]) -> Dict[str, float]:
    if not symbols: return {}
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(f"{FUTURES_BASE}/fapi/v1/ticker/price")
        r.raise_for_status()
        arr = r.json()
    out = {}
    want = set(s.upper() for s in symbols)
    for it in arr:
        s = it.get("symbol")
        if s in want:
            try: out[s] = float(it.get("price"))
            except Exception: pass
    return out

async def _get_context(symbols: List[str], interval: str = "15m") -> Dict[str, Any]:
    if not CONTEXT_URL: return {}
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
    if not WEBHOOK_HMAC_SECRET or not chat_id: return
    if is_muted():
        # שקט — לא שולחים התראות
        return
    payload = {
        "chat_id": chat_id,
        "text": text,
        "reply_to_message_id": reply_to,
        "silent": silent,
        "reply_markup": reply_markup
    }
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
    override = get_near_pct_override()
    if override is not None:
        base = override  # נקבע ידנית מהבוט
    vol = (flags or {}).get("vol_regime","mid")
    chop = bool((flags or {}).get("danger_chop", False))
    if chop and SUPPRESS_CHOP_NEAR:
        return 0.0
    if vol == "high":
        return min(base, NEAR_PCT_HIGHVOL)
    if chop:
        return min(base, NEAR_PCT_CHOP)
    return base

# ---- Digest state ----
def _digest_key(date_str: str) -> str:
    return f"algogpt:digest:{date_str}"

def _seen_digest_today(date_str: str) -> bool:
    if RED:
        return bool(RED.get(_digest_key(date_str)))
    return hasattr(_seen_digest_today, "_d") and getattr(_seen_digest_today, "_d") == date_str

def _mark_digest_sent(date_str: str):
    if RED:
        RED.setex(_digest_key(date_str), 36*3600, "1")
    else:
        setattr(_seen_digest_today, "_d", date_str)

async def _send_daily_digest(active: List[Dict[str, Any]]):
    if not DIGEST_ENABLED or not active: return
    try:
        tz = ZoneInfo(DIGEST_TZ)
    except Exception:
        tz = None
    now = datetime.now(tz) if tz else datetime.now()
    date_str = now.strftime("%Y-%m-%d")
    if now.hour != DIGEST_HOUR or now.minute < DIGEST_MINUTE or _seen_digest_today(date_str):
        return
    if is_muted():
        # לא נשלח בזמן מיוט
        return
    lines = [f"🗞️ *Daily Digest* — {date_str}"]
    for it in active[:30]:
        sym = it.get("symbol","")
        side = it.get("side","")
        entry = _f(it.get("entry")); sl = _f(it.get("sl"))
        tp1 = _f(it.get("tp1")); tp2 = _f(it.get("tp2")); tp3 = _f(it.get("tp3"))
        nowp = _f(it.get("current_price"))
        d1 = f"{_pct(nowp,tp1):.2f}%" if nowp and tp1 else "—"
        ds = f"{_pct(nowp,sl):.2f}%" if nowp and sl else "—"
        lines.append(f"- {sym} {side}: Now `{nowp or '—'}` | TP1 {d1} | SL {ds}")
    text = "\n".join(lines)
    await _notify(text, TELEGRAM_CHAT_ID, reply_to=None, silent=True)
    _mark_digest_sent(date_str)

# ---- GRID helpers ----
def _grid_line_touched(prev_price: float, price: float, line: float) -> bool:
    # מגע/חציה בקו בין שני דגימות
    lo, hi = (prev_price, price) if prev_price <= price else (price, prev_price)
    return lo <= line <= hi

async def step():
    items = await _get_active()
    if not items:
        return

    symbols = [it.get("symbol","") for it in items if it.get("symbol")]
    # מחירים מהירים בקבוצה אחת
    prices = await _get_prices(symbols)
    # דגלי vol/chop לסינון near
    flags_map = await _get_context(symbols, "15m")

    # שמור prev price קליל ב-Redis (או בזיכרון) כדי לזהות חציות לקווי GRID
    prev_key = "algogpt:watchdog:prev_price:"

    for it in items:
        tid = str(it.get("trade_id"))
        sym = it.get("symbol","").upper()
        ttype = (it.get("trade_type") or "FUTURES").upper()
        chat_id = it.get("chat_id") or TELEGRAM_CHAT_ID
        price = prices.get(sym)
        if not price:
            continue

        # prev price (ל-GRID)
        prev_price = None
        if RED:
            pv = RED.get(prev_key + sym)
            if pv: 
                try: prev_price = float(pv)
                except: prev_price = None

        hits = _parse_json_field(it.get("hits"), {"tp1":False,"tp2":False,"tp3":False,"sl":False})
        near = _parse_json_field(it.get("near"), {"tp1":False,"tp2":False,"tp3":False,"sl":False})
        flags = flags_map.get(sym, {})

        # Quiet per trade (לכבות near לטרייד ספציפי)
        quiet_trade = is_trade_quiet(tid)

        if ttype in ("FUTURES","SPOT"):
            side = (it.get("side") or "LONG").upper()
            entry = _f(it.get("entry"))
            sl = _f(it.get("sl"))
            tp1 = _f(it.get("tp1")); tp2 = _f(it.get("tp2")); tp3 = _f(it.get("tp3"))

            # near alerts (אם לא quiet לטרייד)
            if not quiet_trade:
                near_base = _dynamic_near_pct(BASE_NEAR_PCT, flags)
                if near_base > 0.0 and not is_muted():
                    if tp1 and not near.get("tp1") and _pct(price, tp1) <= near_base:
                        near["tp1"] = True
                        await _notify(f"⏳ {sym} כמעט TP1 ({price:.6f} ~ {tp1:.6f})", chat_id, silent=True)
                    if tp2 and not near.get("tp2") and _pct(price, tp2) <= near_base:
                        near["tp2"] = True
                        await _notify(f"⏳ {sym} כמעט TP2 ({price:.6f} ~ {tp2:.6f})", chat_id, silent=True)
                    if tp3 and not near.get("tp3") and _pct(price, tp3) <= near_base:
                        near["tp3"] = True
                        await _notify(f"⏳ {sym} כמעט TP3 ({price:.6f} ~ {tp3:.6f})", chat_id, silent=True)
                    if sl and not near.get("sl") and _pct(price, sl) <= near_base:
                        near["sl"] = True
                        await _notify(f"⚠️ {sym} קרוב ל-SL ({price:.6f} ~ {sl:.6f})", chat_id, silent=True)

            # TP/SL hits (גם אם מיוט — נעדכן סטייט; הודעות רק אם לא מיוט)
            def crossed_up(val): return price >= val
            def crossed_dn(val): return price <= val

            if tp1 and not hits.get("tp1"):
                crossed = crossed_up(tp1) if side=="LONG" else crossed_dn(tp1)
                if crossed:
                    hits["tp1"] = True
                    kb = {"inline_keyboard":[
                        [{"text":"🔒 SL→BE","callback_data":f"slbe:{tid}"}],
                        [{"text":"📊 TP Scale","callback_data":f"tpask:{tid}"}],
                    ]}
                    await _notify(f"✅ {sym} TP1 — לקבע SL ל-BE?", chat_id, reply_to=it.get("message_id"), silent=False, reply_markup=kb)
                    if SL_BE_ON_TP1 and entry:
                        await _update_trade(tid, {"hits": json.dumps(hits), "near": json.dumps(near), "sl": float(entry)})
                        await _notify(f"🔒 SL הוזז ל-BE ({entry:.6f})", chat_id, reply_to=it.get("message_id"), silent=False)
                    else:
                        await _update_trade(tid, {"hits": json.dumps(hits), "near": json.dumps(near)})
                    continue

            if tp2 and not hits.get("tp2"):
                crossed = crossed_up(tp2) if side=="LONG" else crossed_dn(tp2)
                if crossed:
                    hits["tp2"] = True
                    await _update_trade(tid, {"hits": json.dumps(hits), "near": json.dumps(near)})
                    await _notify(f"✅ {sym} TP2", chat_id, reply_to=it.get("message_id"), silent=False)
                    continue

            if tp3 and not hits.get("tp3"):
                crossed = crossed_up(tp3) if side=="LONG" else crossed_dn(tp3)
                if crossed:
                    hits["tp3"] = True
                    await _update_trade(tid, {"hits": json.dumps(hits), "near": json.dumps(near)})
                    await _notify(f"✅ {sym} TP3 — סגירה לפי נוהל", chat_id, reply_to=it.get("message_id"), silent=False)
                    continue

            if sl and not hits.get("sl"):
                crossed = crossed_dn(sl) if side=="LONG" else crossed_up(sl)
                if crossed:
                    hits["sl"] = True
                    await _update_trade(tid, {"hits": json.dumps(hits), "near": json.dumps(near)})
                    await _notify(f"🛑 {sym} SL הופעל", chat_id, reply_to=it.get("message_id"), silent=False)
                    continue

        elif ttype == "GRID" and is_grid_alerts_enabled():
            # נשלח “מגע בקו” פעם ראשונה לכל קו
            grid_lines = it.get("grid_lines")
            if isinstance(grid_lines, str):
                try: grid_lines = json.loads(grid_lines)
                except Exception: grid_lines = []
            if isinstance(grid_lines, list) and grid_lines:
                hit_key = f"algogpt:grid:hits:{tid}"
                done: set = set()
                if RED:
                    done = set(RED.smembers(hit_key) or [])
                # לחסכון ספאם: צריך prev_price, אחרת נבדוק “קרוב” בלבד
                for line in grid_lines:
                    try: ln = float(line)
                    except: continue
                    touched = False
                    if prev_price is not None:
                        touched = _grid_line_touched(prev_price, price, ln)
                    else:
                        touched = (abs(price - ln)/ln) <= 0.0005  # ~0.05% “בקרבת קו”
                    if touched and f"{ln:.6f}" not in done:
                        await _notify(f"⚡ GRID {sym} מגע בקו `{ln:.6f}`", chat_id, reply_to=it.get("message_id"), silent=True)
                        if RED: RED.sadd(hit_key, f"{ln:.6f}")

        # עדכון prev_price לזיהוי חציות סה״כ
        if RED:
            RED.setex(prev_key + sym, 300, f"{price:.12f}")

    await _send_daily_digest(items)

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


