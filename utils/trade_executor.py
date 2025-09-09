# utils/trade_executor.py
from __future__ import annotations
import os, math, time, logging, asyncio, json
from typing import Optional, Dict, Any, List, Tuple
import httpx

from utils.binance_client import (
    get_price, futures_mark_price, set_leverage, futures_create_order,
    get_symbol_filters, get_all_orders, futures_cancel_order, get_futures_client
)

log = logging.getLogger("algogpt.trade_executor")

# ─────────── Policy & Defaults (ENV) ───────────
ALLOW_MARKET_ENTRY = os.getenv("ALLOW_MARKET_ENTRY", "1") in ("1","true","yes","on")

# כניסה היברידית: LIMIT Maker סביב המחיר + STOP (breakout) בצד השני
ENTRY_BAND_BPS    = float(os.getenv("ENTRY_BAND_BPS", "8.5"))   # ★ ברירת מחדל 8.5bps
STOP_BAND_BPS     = float(os.getenv("STOP_BAND_BPS",  "10"))
ESCALATE_AFTER_S  = float(os.getenv("ESCALATE_AFTER_SEC", "10"))
ESCALATE_SLIP_BPS = float(os.getenv("ESCALATE_SLIPPAGE_BPS", "15"))

# דיוק SL/TP (limit-variants)
SL_LIMIT_OFFSET_BPS = float(os.getenv("SL_LIMIT_OFFSET_BPS", "8"))
TP_LIMIT_OFFSET_BPS = float(os.getenv("TP_LIMIT_OFFSET_BPS", "8"))

# איכות סיגנל (Gate) — ★ מינימום ציון 8.5 כברירת־מחדל
MIN_QUALITY_SCORE = float(os.getenv("MIN_QUALITY_SCORE", "8.5"))
MAX_ATR_PCT       = float(os.getenv("MAX_ATR_PCT", "2.5"))  # ATR(14) כאחוז מחיר
MIN_VOLUME        = float(os.getenv("MIN_VOLUME", "0"))     # אם 0 -> מתעלמים

# דיוקים כלליים
DEFAULT_QTY_STEP = float(os.getenv("DEFAULT_QTY_STEP", "0.001"))
DEFAULT_TICK     = float(os.getenv("DEFAULT_PRICE_TICK", "0.01"))
DEFAULT_MIN_NOT  = float(os.getenv("MIN_NOTIONAL_USDT", "5"))

# Telegram
BOT_TOKEN       = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
API_BASE        = f"https://api.telegram.org/bot{BOT_TOKEN}" if BOT_TOKEN else ""
CONFIRM_TTL_SEC = int(os.getenv("CONFIRM_TTL_SEC", "180"))

# Redis (אופציונלי)
REDIS_URL = os.getenv("REDIS_URL", "").strip()
try:
    import redis  # type: ignore
    _redis_available = bool(REDIS_URL)
except Exception:
    _redis_available = False

# ─────────── Quantize helpers ───────────
def _decimals(step_str: str) -> int:
    if "." not in step_str: return 0
    frac = step_str.split(".")[1].rstrip("0")
    return len(frac)

def _filters(symbol: str) -> Dict[str, Any]:
    return get_symbol_filters(symbol) or {}

def _q_price(symbol: str, price: float) -> Tuple[str, float]:
    f = _filters(symbol); tick = float(f.get("tickSize") or DEFAULT_TICK) or DEFAULT_TICK
    decs = _decimals(str(f.get("tickSize") or DEFAULT_TICK))
    steps = round(price / tick); p = steps * tick
    s = f"{p:.{decs}f}"
    return s, float(s)

def _q_qty(symbol: str, qty: float) -> Tuple[str, float]:
    f = _filters(symbol); step = float(f.get("stepSize") or DEFAULT_QTY_STEP) or DEFAULT_QTY_STEP
    decs = _decimals(str(f.get("stepSize") or DEFAULT_QTY_STEP))
    steps = math.floor(qty / step); q = max(step, steps * step)
    s = f"{q:.{decs}f}"
    return s, float(s)

def _min_notional(symbol: str) -> float:
    f = _filters(symbol); mn = f.get("minNotional")
    try: return float(mn) if mn is not None else DEFAULT_MIN_NOT
    except Exception: return DEFAULT_MIN_NOT

def _ensure_min_notional(symbol: str, price: float, qty: float) -> float:
    mn = _min_notional(symbol)
    if price * qty >= mn: return qty
    need = mn / max(price, 1e-9)
    _, q2 = _q_qty(symbol, need)
    return q2

def _calc_qty(symbol: str, price: float, budget: Optional[float], leverage: int, quantity: Optional[float]) -> float:
    if quantity and quantity > 0:
        q = float(quantity)
    else:
        if not budget or budget <= 0: raise ValueError("Either positive budget or quantity must be provided")
        usd = float(budget) * float(leverage)
        q = usd / price
    q = _ensure_min_notional(symbol, price, q)
    _, q = _q_qty(symbol, q)
    return q

def _offset_bps(base: float, bps: float, sign: int) -> float:
    return base * (1.0 + sign * (bps / 10000.0))

# ─────────── Telegram Confirm Store (memory/redis) ───────────
class ConfirmStore:
    _mem: Dict[str, Dict[str, Any]] = {}  # cid -> record
    _r = None
    try:
        if _redis_available:
            _r = redis.Redis.from_url(REDIS_URL, decode_responses=True)  # type: ignore
    except Exception as e:
        log.warning("Redis unavailable: %s", e)
        _r = None

    @classmethod
    def create(cls, chat_id: int, payload: Dict[str, Any], ttl: int = CONFIRM_TTL_SEC) -> str:
        cid = f"cid_{int(time.time()*1000)}_{os.getpid()}_{abs(hash(os.urandom(8)))}"
        rec = {"status": "pending", "payload": payload, "chat_id": chat_id, "created_at": time.time()}
        if cls._r:
            cls._r.setex(f"confirm:{cid}", ttl, json.dumps(rec))
        else:
            cls._mem[cid] = rec
        return cid

    @classmethod
    def _load(cls, cid: str) -> Optional[Dict[str, Any]]:
        if cls._r:
            v = cls._r.get(f"confirm:{cid}")
            return json.loads(v) if v else None
        return cls._mem.get(cid)

    @classmethod
    def get(cls, cid: str) -> Optional[Dict[str, Any]]:
        rec = cls._load(cid)
        if not rec: return None
        if rec.get("status") == "pending" and time.time() - rec["created_at"] > CONFIRM_TTL_SEC:
            rec["status"] = "expired"
            if cls._r:
                cls._r.setex(f"confirm:{cid}", 60, json.dumps(rec))
            else:
                cls._mem[cid] = rec
        return rec

    @classmethod
    def _save(cls, cid: str, rec: Dict[str, Any]) -> None:
        if cls._r:
            cls._r.setex(f"confirm:{cid}", 60, json.dumps(rec))
        else:
            cls._mem[cid] = rec

    @classmethod
    def approve(cls, cid: str, approver: str = "") -> None:
        rec = cls.get(cid)
        if not rec: return
        rec["status"] = "approved"; rec["approver"] = approver; cls._save(cid, rec)

    @classmethod
    def reject(cls, cid: str, approver: str = "") -> None:
        rec = cls.get(cid)
        if not rec: return
        rec["status"] = "rejected"; rec["approver"] = approver; cls._save(cid, rec)

async def send_confirm_request(chat_id: int, title: str, summary_html: str, cid: str) -> Dict[str, Any]:
    if not BOT_TOKEN:
        return {"ok": False, "error": "BOT_TOKEN missing"}
    kb = {
        "inline_keyboard": [[
            {"text": "✅ אישור", "callback_data": f"CONFIRM:APPROVE:{cid}"},
            {"text": "❌ ביטול", "callback_data": f"CONFIRM:REJECT:{cid}"}
        ]]
    }
    text = f"<b>{title}</b>\n{summary_html}\n\n<b>CID:</b> <code>{cid}</code>"
    async with httpx.AsyncClient(timeout=10.0) as cli:
        r = await cli.post(f"{API_BASE}/sendMessage", data={
            "chat_id": chat_id, "text": text, "parse_mode": "HTML",
            "disable_web_page_preview": True, "reply_markup": json.dumps(kb)
        })
        try:
            return r.json()
        except Exception:
            return {"ok": False, "error": f"http {r.status_code}"}

async def require_approval(chat_id: int, payload: Dict[str, Any]) -> Dict[str, Any]:
    cid = ConfirmStore.create(chat_id, payload, ttl=CONFIRM_TTL_SEC)
    title = "אישור טרייד"
    summary = (
        f"<b>{payload.get('symbol')}</b> {payload.get('side')}  "
        f"qty={payload.get('qty')} lev={payload.get('leverage')}<br/>"
        f"כניסה: HYBRID (Limit±{ENTRY_BAND_BPS}bps / Stop±{STOP_BAND_BPS}bps)"
    )
    await send_confirm_request(chat_id, title, summary, cid)
    t0 = time.time()
    while time.time() - t0 < CONFIRM_TTL_SEC:
        rec = ConfirmStore.get(cid)
        if rec and rec.get("status") in ("approved", "rejected", "expired"):
            return {"cid": cid, "status": rec["status"]}
        await asyncio.sleep(0.5)
    return {"cid": cid, "status": "expired"}

# ─────────── Light indicators (no pandas) ───────────
def _ema(vals: List[float], period: int) -> List[float]:
    k = 2 / (period + 1)
    ema = []
    s = None
    for v in vals:
        s = v if s is None else (v * k + s * (1 - k))
        ema.append(s)
    return ema

def _atr_from_klines(kl: List[List[float]], period: int = 14) -> float:
    trs: List[float] = []
    prev_close = None
    for row in kl:
        high = float(row[2]); low = float(row[3]); close = float(row[4])
        if prev_close is None:
            tr = high - low
        else:
            tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        trs.append(tr)
        prev_close = close
    if len(trs) < period: return trs[-1] if trs else 0.0
    return _ema(trs, period)[-1]

def _fetch_klines_raw(symbol: str, interval: str = "1



































































