# workers/trade_watchdog.py
from __future__ import annotations
import os, json, time, asyncio, math, httpx
from dataclasses import dataclass
from typing import Dict, Any, List, Optional
from datetime import datetime
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
load_dotenv(override=False)

# --- Config ---
ALERTS_BASE   = os.getenv("ALERTS_BASE", "http://localhost:8000").rstrip("/")
API_BEARER    = os.getenv("API_BEARER_TOKEN","")
HMAC_SECRET   = (os.getenv("HMAC_SECRET","")).encode()

# מקורות קונטקסט ומעקב
CONTEXT_BATCH_URL = os.getenv("CONTEXT_BATCH_URL","").strip() # e.g. https://host/context/batch?compact=1&interval=15m&limit=120&symbols={csv}
CONTEXT_URL       = os.getenv("CONTEXT_URL","").strip()       # fallback per symbol
CONTEXT_TOKEN     = os.getenv("CONTEXT_TOKEN","").strip()

# אינטרוולים
POLL_SECONDS        = int(os.getenv("WATCHDOG_POLL_SECONDS","20"))      # כל כמה זמן למשוך מחירים/קונטקסט
HEARTBEAT_MINUTES   = int(os.getenv("HEARTBEAT_MINUTES","30"))          # כל כמה זמן לעדכן “מצב” אם לא קרה אירוע
NEAR_PCT_BASE       = float(os.getenv("NEAR_PCT_BASE","0.35"))          # קרבה ל-TP/SL באחוזים מהמחיר
COOLDOWN_ALERT_SEC  = int(os.getenv("COOLDOWN_ALERT_SEC","90"))         # מניעת ספאם התראות עבור אותו אירוע
PRICE_DELTA_MIN_PCT = float(os.getenv("PRICE_DELTA_MIN_PCT","0.05"))    # מינ’ שינוי מחירים לאינטרציה

TZ_NAME = os.getenv("TZ","Asia/Jerusalem")

# התאמת ספים לפי שעות מקומיות (חם/רגוע)
HOT_HOURS   = [16,17,18,19,20,21,22,23,0,1]       # מקומיות (16:00–01:59 ~ US+EU overlap)
CALM_HOURS  = [4,5,6,7,8,9]                        # בוקר רגוע
NEAR_MULT_HOT  = float(os.getenv("NEAR_MULT_HOT","0.8"))   # בסשן חם – נקל (0.8×)
NEAR_MULT_CALM = float(os.getenv("NEAR_MULT_CALM","1.2"))  # בסשן רגוע – נחמיר (1.2×)

# ניהול מצב מקומי
_last_event_ts: Dict[str, float] = {}         # (trade_id:event_key) -> ts
_last_price: Dict[str, float] = {}            # symbol -> price
_last_trend: Dict[str, str] = {}              # symbol -> {"UP","DOWN","NONE"}
_last_heartbeat: Dict[str, float] = {}        # trade_id -> ts

# --- Helpers ---
def _hmac_hex(body: bytes) -> str:
    if not HMAC_SECRET: return ""
    import hmac, hashlib
    return hmac.new(HMAC_SECRET, body, hashlib.sha256).hexdigest()

def _now() -> float: return time.time()

def _local_hour() -> int:
    return datetime.now(ZoneInfo(TZ_NAME)).hour

def _near_pct_runtime() -> float:
    hr = _local_hour()
    if hr in HOT_HOURS: return NEAR_PCT_BASE * NEAR_MULT_HOT
    if hr in CALM_HOURS: return NEAR_PCT_BASE * NEAR_MULT_CALM
    return NEAR_PCT_BASE

def _cooldown(key: str, sec: int) -> bool:
    ts = _last_event_ts.get(key, 0)
    if _now() - ts < sec: return False
    _last_event_ts[key] = _now()
    return True

def _fmt(x) -> str:
    try:
        v = float(x)
        return f"{v:.6f}"
    except Exception:
        return "—"

def _percent(a: float, b: float) -> float:
    if b == 0: return 0.0
    return 100.0 * (a - b) / b

# --- HTTP calls ---
async def get_active_trades() -> List[Dict[str, Any]]:
    headers = {"Authorization": f"Bearer {API_BEARER}"} if API_BEARER else {}
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(f"{ALERTS_BASE}/alerts/trades/active", headers=headers)
        r.raise_for_status()
        data = r.json()
        return data.get("items", [])

async def send_analysis(chat_id: str|int, text: str, reply_to: Optional[int]=None, silent: bool=True):
    body = {"text": text, "chat_id": chat_id, "reply_to_message_id": reply_to, "silent": silent}
    raw = json.dumps(body, separators=(",", ":"), ensure_ascii=False).encode()
    headers = {"Authorization": f"Bearer {API_BEARER}", "Content-Type":"application/json", "X-Idempotency-Key": f"wd-{int(_now())}-{hash(text)%9999}"}
    sig = _hmac_hex(raw)
    if sig: headers["X-Signature"] = sig
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.post(f"{ALERTS_BASE}/alerts/analysis", content=raw, headers=headers)
        r.raise_for_status()

async def fetch_ctx_batch(symbols: List[str]) -> Dict[str, Dict[str, Any]]:
    if not CONTEXT_BATCH_URL:
        return {}
    csv = ",".join(symbols)
    url = CONTEXT_BATCH_URL.replace("{csv}", csv)
    headers = {"Authorization": f"Bearer {CONTEXT_TOKEN}"} if CONTEXT_TOKEN else {}
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(url, headers=headers)
        r.raise_for_status()
        data = r.json()
        out = {}
        for it in data.get("items", []):
            sym = (it.get("symbol") or "").upper()
            if sym: out[sym] = it
        return out

# --- Core logic ---
@dataclass
class Levels:
    entry: float
    sl: float
    tp1: float
    tp2: Optional[float]
    tp3: Optional[float]

def _nearest_target(levels: Levels, price: float, side: str) -> tuple[str, float]:
    """
    מחזיר (“tp1”/“tp2”/“tp3”/“sl”, מרחק באחוזים).
    """
    candidates: List[tuple[str,float]] = []
    def dist_pct(a,b): return abs(a-b)/b * 100.0 if b>0 else 999.0
    # tp
    if levels.tp1: candidates.append(("tp1", dist_pct(levels.tp1, price)))
    if levels.tp2: candidates.append(("tp2", dist_pct(levels.tp2, price)))
    if levels.tp3: candidates.append(("tp3", dist_pct(levels.tp3, price)))
    # sl
    if levels.sl: candidates.append(("sl", dist_pct(levels.sl, price)))
    candidates.sort(key=lambda x: x[1])
    return candidates[0] if candidates else ("", 999.0)

def _trend_label(filters: Dict[str, Any]) -> str:
    if filters.get("trending_up"): return "UP"
    if filters.get("trending_down"): return "DOWN"
    return "NONE"

async def loop_watchdog():
    while True:
        try:
            trades = await get_active_trades()
            if not trades:
                await asyncio.sleep(POLL_SECONDS)
                continue

            symbols = sorted({ str(t["symbol"]).upper() for t in trades })
            # הוסף BTC/ETH לקבלת “עוגן” (ללא עומס)
            if "BTCUSDT" not in symbols: symbols.append("BTCUSDT")
            if "ETHUSDT" not in symbols: symbols.append("ETHUSDT")

            ctx_map = await fetch_ctx_batch(symbols)
            near_pct = _near_pct_runtime()

            for rec in trades:
                sym = str(rec["symbol"]).upper()
                chat_id = rec.get("chat_id")
                mid = rec.get("message_id")

                # מחיר וקונטקסט
                ctx = ctx_map.get(sym) or {}
                price = float(ctx.get("price") or rec.get("current_price") or 0.0)
                if price <= 0: continue

                # שליטה בעדכון רק אם המחיר זז
                prev = _last_price.get(sym)
                if prev is not None and abs(_percent(price, prev)) < PRICE_DELTA_MIN_PCT:
                    # לא זז משמעותית — נבדוק רק אירועי זמן (Heartbeat)
                    pass
                _last_price[sym] = price

                lv = Levels(
                    entry=float(rec.get("entry") or 0.0),
                    sl=float(rec.get("sl") or 0.0),
                    tp1=float(rec.get("tp1") or 0.0),
                    tp2=float(rec.get("tp2") or 0.0) if rec.get("tp2") else None,
                    tp3=float(rec.get("tp3") or 0.0) if rec.get("tp3") else None,
                )
                side = str(rec.get("side","")).upper()

                # איתור יעד קרוב
                tgt_name, tgt_dist = _nearest_target(lv, price, side)

                # מצב טרנד + שינוי מגמה
                filters = (ctx.get("filters") or {}) if isinstance(ctx, dict) else {}
                cur_trend = _trend_label(filters)
                last_tr = _last_trend.get(sym, "NONE")
                if cur_trend != last_tr:
                    _last_trend[sym] = cur_trend
                    key = f"{rec['trade_id']}:trend:{cur_trend}"
                    if _cooldown(key, COOLDOWN_ALERT_SEC):
                        ttxt = f"📈 שינוי מגמה ב־*{sym}*: `{last_tr}` → `{cur_trend}` (Now `{_fmt(price)}`)"
                        await send_analysis(chat_id, ttxt, reply_to=mid, silent=True)

                # קרבה ליעד (TP/SL)
                if tgt_name and tgt_dist <= near_pct:
                    key = f"{rec['trade_id']}:near:{tgt_name}"
                    if _cooldown(key, COOLDOWN_ALERT_SEC):
                        d = f"{tgt_dist:.2f}%"
                        ttxt = f"⏳ *{sym}* קרוב ל־*{tgt_name.upper()}* ({d}). Now `{_fmt(price)}`"
                        # אם יש עוגן BTC/ETH — תן הקשר קצר
                        btc = ctx_map.get("BTCUSDT", {})
                        eth = ctx_map.get("ETHUSDT", {})
                        if (btc.get('filters') or {}).get('trending_up'): ttxt += " | BTC:↑"
                        elif (btc.get('filters') or {}).get('trending_down'): ttxt += " | BTC:↓"
                        if (eth.get('filters') or {}).get('trending_up'): ttxt += " | ETH:↑"
                        elif (eth.get('filters') or {}).get('trending_down'): ttxt += " | ETH:↓"
                        await send_analysis(chat_id, ttxt, reply_to=mid, silent=True)

                # פגיעה ביעד בפועל (חצייה)
                def crossed(level: float, kind: str) -> bool:
                    if level <= 0: return False
                    # קרוס פשוט — מתאים לשני הכיוונים
                    hit = (price >= level) if level >= lv.entry else (price <= level)
                    if not hit: return False
                    key = f"{rec['trade_id']}:hit:{kind}"
                    return _cooldown(key, COOLDOWN_ALERT_SEC)

                if lv.tp1 and crossed(lv.tp1, "tp1"):
                    await send_analysis(chat_id, f"✅ *{sym}* הגיע *TP1* @ `{_fmt(lv.tp1)}` (Now `{_fmt(price)}`)", reply_to=mid, silent=False)
                if lv.tp2 and crossed(lv.tp2, "tp2"):
                    await send_analysis(chat_id, f"✅ *{sym}* הגיע *TP2* @ `{_fmt(lv.tp2)}` (Now `{_fmt(price)}`)", reply_to=mid, silent=False)
                if lv.tp3 and crossed(lv.tp3, "tp3"):
                    await send_analysis(chat_id, f"✅ *{sym}* הגיע *TP3* @ `{_fmt(lv.tp3)}` (Now `{_fmt(price)}`)", reply_to=mid, silent=False)
                if lv.sl and crossed(lv.sl, "sl"):
                    await send_analysis(chat_id, f"❌ *{sym}* פגע *SL* @ `{_fmt(lv.sl)}` (Now `{_fmt(price)}`)", reply_to=mid, silent=False)

                # Heartbeat מרווח (עם “סיכוי רגעי” קל — לא GPT)
                last_hb = _last_heartbeat.get(rec["trade_id"], 0)
                if _now() - last_hb >= HEARTBEAT_MINUTES*60:
                    _last_heartbeat[rec["trade_id"]] = _now()
                    # הערכת סיכוי רגעית מאוד “דקה”: יחס מרחקים ל-TP1/SL + מצב מגמה
                    def dist(p, x): 
                        try: return abs(p-x)/p
                        except: return 1.0
                    d_tp = dist(price, lv.tp1) if lv.tp1 else 1.0
                    d_sl = dist(price, lv.sl) if lv.sl else 1.0
                    odds = 50.0
                    if d_tp + d_sl > 0:
                        odds = 100.0 * (1.0 - (d_tp / (d_tp + d_sl)))   # קרוב יותר ל-TP → גבוה יותר
                    # הטיה קלה לפי מגמה
                    if cur_trend == "UP" and side == "LONG": odds += 5
                    if cur_trend == "DOWN" and side == "SHORT": odds += 5
                    if cur_trend == "UP" and side == "SHORT": odds -= 5
                    if cur_trend == "DOWN" and side == "LONG": odds -= 5
                    odds = max(5.0, min(95.0, odds))
                    hb = f"📬 *Heartbeat* #{rec['trade_id']} — *{sym}* Now `{_fmt(price)}` | TP1 `{_fmt(lv.tp1)}` SL `{_fmt(lv.sl)}` | סיכוי רגעי ל-TP1 ≈ *{odds:.0f}%* | מגמה `{cur_trend}` | חלון: {_near_pct_runtime():.2f}%"
                    await send_analysis(chat_id, hb, reply_to=mid, silent=True)

        except Exception as e:
            print("[watchdog] error:", e)

        await asyncio.sleep(POLL_SECONDS)

if __name__ == "__main__":
    if not API_BEARER: raise SystemExit("API_BEARER_TOKEN missing")
    asyncio.run(loop_watchdog())




