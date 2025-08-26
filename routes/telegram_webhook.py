# workers/trade_watchdog.py
from __future__ import annotations
import os, json, time, asyncio, math, httpx
from dataclasses import dataclass
from typing import Dict, Any, List, Optional
from datetime import datetime
from zoneinfo import ZoneInfo
from dotenv import load_dotenv
load_dotenv(override=False)

ALERTS_BASE   = os.getenv("ALERTS_BASE", "http://localhost:8000").rstrip("/")
API_BEARER    = os.getenv("API_BEARER_TOKEN","")
HMAC_SECRET   = (os.getenv("HMAC_SECRET","")).encode()

CONTEXT_BATCH_URL = os.getenv("CONTEXT_BATCH_URL","").strip()
CONTEXT_URL       = os.getenv("CONTEXT_URL","").strip()
CONTEXT_TOKEN     = os.getenv("CONTEXT_TOKEN","").strip()

POLL_SECONDS        = int(os.getenv("WATCHDOG_POLL_SECONDS","20"))
HEARTBEAT_MINUTES   = int(os.getenv("HEARTBEAT_MINUTES","30"))
NEAR_PCT_BASE       = float(os.getenv("NEAR_PCT_BASE","0.35"))
COOLDOWN_ALERT_SEC  = int(os.getenv("COOLDOWN_ALERT_SEC","90"))
PRICE_DELTA_MIN_PCT = float(os.getenv("PRICE_DELTA_MIN_PCT","0.05"))
TZ_NAME = os.getenv("TZ","Asia/Jerusalem")
HOT_HOURS   = [int(x) for x in os.getenv("HOT_HOURS","16,17,18,19,20,21,22,23,0,1").split(",") if x.strip().isdigit()]
CALM_HOURS  = [int(x) for x in os.getenv("CALM_HOURS","4,5,6,7,8,9").split(",") if x.strip().isdigit()]
NEAR_MULT_HOT  = float(os.getenv("NEAR_MULT_HOT","0.8"))
NEAR_MULT_CALM = float(os.getenv("NEAR_MULT_CALM","1.2"))

ENTRY_ZONE_PCT     = float(os.getenv("ENTRY_ZONE_PCT","0.15"))
ENTRY_ZONE_ALERT   = os.getenv("ENTRY_ZONE_ALERT","1").lower() in ("1","true","yes")
ANCHOR_FLIP_WARN_COUNT = int(os.getenv("ANCHOR_FLIP_WARN_COUNT","2"))

_last_event_ts: Dict[str, float] = {}
_last_price: Dict[str, float] = {}
_last_trend: Dict[str, str] = {}
_last_heartbeat: Dict[str, float] = {}
_anchor_state: Dict[str, int] = {}
_zone_notified: Dict[str, bool] = {}
_grid_hits: Dict[str, List[int]] = {}  # trade_id -> indices of hit lines

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

@dataclass
class Levels:
    entry: float
    sl: float
    tp1: float
    tp2: Optional[float]
    tp3: Optional[float]

def _nearest_target(levels: Levels, price: float) -> tuple[str, float]:
    candidates: List[tuple[str,float]] = []
    def dist_pct(a,b): return abs(a-b)/b * 100.0 if b>0 else 999.0
    if levels.tp1: candidates.append(("tp1", dist_pct(levels.tp1, price)))
    if levels.tp2: candidates.append(("tp2", dist_pct(levels.tp2, price)))
    if levels.tp3: candidates.append(("tp3", dist_pct(levels.tp3, price)))
    if levels.sl:  candidates.append(("sl",  dist_pct(levels.sl,  price)))
    candidates.sort(key=lambda x: x[1])
    return candidates[0] if candidates else ("", 999.0)

def _trend_label(filters: Dict[str, Any]) -> str:
    if filters.get("trending_up"): return "UP"
    if filters.get("trending_down"): return "DOWN"
    return "NONE"

def _grid_lines(rec: Dict[str, Any]) -> List[float]:
    # נשמר ע"י trade_sink כ-json אם קיים
    try:
        if rec.get("grid_lines"):
            return [float(x) for x in json.loads(rec["grid_lines"])]
    except Exception:
        pass
    # אחרת — נחשב דינמית
    try:
        gmin = float(rec.get("grid_min") or 0)
        gmax = float(rec.get("grid_max") or 0)
        L    = int(rec.get("grid_levels") or 0)
        if gmin > 0 and gmax > 0 and L >= 2:
            step = (gmax - gmin) / (L - 1)
            return [gmin + i * step for i in range(L)]
    except Exception:
        pass
    return []

async def loop_watchdog():
    while True:
        try:
            trades = await get_active_trades()
            if not trades:
                await asyncio.sleep(POLL_SECONDS)
                continue

            symbols = sorted({ str(t["symbol"]).upper() for t in trades })
            if "BTCUSDT" not in symbols: symbols.append("BTCUSDT")
            if "ETHUSDT" not in symbols: symbols.append("ETHUSDT")

            ctx_map = await fetch_ctx_batch(symbols)
            near_pct = _near_pct_runtime()

            # Anchor (BTC)
            btc_trend = "NONE"
            btc = ctx_map.get("BTCUSDT", {})
            if btc:
                btc_f = (btc.get("filters") or {})
                btc_trend = "UP" if btc_f.get("trending_up") else ("DOWN" if btc_f.get("trending_down") else "NONE")
                cnt = _anchor_state.get("BTCUSDT", 0)
                if btc_trend == "UP":   cnt = cnt + 1 if cnt >= 0 else 1
                elif btc_trend == "DOWN": cnt = cnt - 1 if cnt <= 0 else -1
                else: cnt = 0
                _anchor_state["BTCUSDT"] = cnt

            for rec in trades:
                sym = str(rec["symbol"]).upper()
                chat_id = rec.get("chat_id")
                mid = rec.get("message_id")
                ttype = str(rec.get("trade_type","FUTURES")).upper()

                ctx = ctx_map.get(sym) or {}
                price = float(ctx.get("price") or rec.get("current_price") or 0.0)
                if price <= 0: 
                    continue

                prev = _last_price.get(sym)
                if prev is not None and abs(_percent(price, prev)) < PRICE_DELTA_MIN_PCT:
                    pass
                _last_price[sym] = price

                filters = (ctx.get("filters") or {}) if isinstance(ctx, dict) else {}
                cur_trend = _trend_label(filters)
                last_tr = _last_trend.get(sym, "NONE")
                if cur_trend != last_tr:
                    _last_trend[sym] = cur_trend
                    key = f"{rec['trade_id']}:trend:{cur_trend}"
                    if _cooldown(key, COOLDOWN_ALERT_SEC):
                        await send_analysis(chat_id, f"📈 שינוי מגמה ב־*{sym}*: `{last_tr}` → `{cur_trend}` (Now `{_fmt(price)}`)", reply_to=mid, silent=True)

                # Anchor flip guard (FUTURES בלבד)
                cnt = _anchor_state.get("BTCUSDT", 0)
                if ttype == "FUTURES" and ANCHOR_FLIP_WARN_COUNT > 0 and rec.get("side"):
                    side = str(rec["side"]).upper()
                    if side == "LONG" and cnt <= -ANCHOR_FLIP_WARN_COUNT:
                        if _cooldown(f"{rec['trade_id']}:anchor:bear", COOLDOWN_ALERT_SEC*2):
                            await send_analysis(chat_id, f"⚠️ *BTC Anchor* BEAR ({abs(cnt)} רצופים). LONG ב־{sym} — זהירות.", reply_to=mid, silent=True)
                    if side == "SHORT" and cnt >= ANCHOR_FLIP_WARN_COUNT:
                        if _cooldown(f"{rec['trade_id']}:anchor:bull", COOLDOWN_ALERT_SEC*2):
                            await send_analysis(chat_id, f"⚠️ *BTC Anchor* BULL ({abs(cnt)} רצופים). SHORT ב־{sym} — זהירות.", reply_to=mid, silent=True)

                # סוג-ספציפי
                if ttype in ("FUTURES","SPOT"):
                    lv = Levels(
                        entry=float(rec.get("entry") or 0.0),
                        sl=float(rec.get("sl") or 0.0),
                        tp1=float(rec.get("tp1") or 0.0),
                        tp2=float(rec.get("tp2") or 0.0) if rec.get("tp2") else None,
                        tp3=float(rec.get("tp3") or 0.0) if rec.get("tp3") else None,
                    )
                    side = str(rec.get("side","")).upper()

                    # “כניסה לאזור”
                    if ENTRY_ZONE_ALERT and lv.entry and ENTRY_ZONE_PCT > 0:
                        band = ENTRY_ZONE_PCT/100.0 * lv.entry
                        in_zone = (lv.entry - band <= price <= lv.entry + band)
                        zkey = f"{rec['trade_id']}:zone"
                        if in_zone and not _zone_notified.g_




