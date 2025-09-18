# routes/scan_top_volume.py
from __future__ import annotations
import os, time, math
from typing import Optional, Dict, Any, List
from fastapi import APIRouter, Query, Depends

try:
    from utils.auth import require_bearer_token  # type: ignore
except Exception:
    def require_bearer_token(): return None

from utils.telegram_notifier_core import telegram_send_markdown, build_trade_message
from utils.estimation import suggest_entry, compute_sl_tp, probabilities, eta_minutes, profit_usd, brief_reason

# לקליטת מחיר/קווים של BTC לצורך הקשר שוק
try:
    from utils.get_klines import get_klines_sync  # קיימת אצלך ב-startup
except Exception:
    get_klines_sync = None

try:
    from utils.binance_client import get_price
except Exception:
    def get_price(symbol: str) -> float: return 0.0

router = APIRouter(prefix="/scan", tags=["Scanner"], dependencies=[Depends(require_bearer_token)])

_STATE: Dict[tuple, Dict[str, Any]] = {}
_LAST_GOOD_TS = 0.0

def _passes(sig: Dict[str, Any], min_score: float, require_side: bool) -> bool:
    score_ok = float(sig.get("score") or 0) >= float(min_score or 0)
    side = (sig.get("side") or "").upper()
    side_ok = (not require_side) or (side in ("BUY", "SELL"))
    return score_ok and side_ok

def _should_notify(sig: Dict[str, Any], min_score: float, rearm_score: float, dedupe_window_sec: int) -> bool:
    key = (sig["symbol"], sig["timeframe"])
    now = time.time()
    st = _STATE.get(key) or {"state":"disarmed", "last_ts":0.0, "last_score":0.0}
    score = float(sig.get("score") or 0)

    changed = False
    if st["state"] == "disarmed":
        if score >= min_score:
            st["state"] = "armed"
            changed = True
    else:
        if score < rearm_score:
            st["state"] = "disarmed"

    recently = (now - st["last_ts"]) < max(0, dedupe_window_sec)
    st["last_ts"] = now; st["last_score"] = score
    _STATE[key] = st
    return changed and not recently

def _ema(series: List[float], period: int) -> float:
    if not series or period <= 1: return series[-1] if series else 0.0
    k = 2.0 / (period + 1.0)
    ema = series[0]
    for x in series[1:]:
        ema = x * k + ema * (1 - k)
    return ema

def _btc_market_ctx(timeframe: str) -> Optional[Dict[str, Any]]:
    """הפקת הקשר שוק BTC: מחיר, EMA21/50, מגמה UP/DOWN/SIDE."""
    try:
        price = float(get_price("BTCUSDT") or 0.0)
    except Exception:
        price = 0.0

    if get_klines_sync:
        try:
            kl = get_klines_sync("BTCUSDT", interval=timeframe, limit=120)
            closes = [float(x[4]) for x in kl if len(x) >= 5]  # מחיר סגירה
            if len(closes) >= 60:
                e21 = _ema(closes[-60:], 21)
                e50 = _ema(closes[-60:], 50)
                if e21 > e50 * 1.002: trend = "UP"
                elif e21 < e50 * 0.998: trend = "DOWN"
                else: trend = "SIDE"
                return {"price": price, "ema21": e21, "ema50": e50, "trend": trend}
        except Exception:
            pass

    # fallback מינימלי
    return {"price": price, "ema21": 0.0, "ema50": 0.0, "trend": "SIDE"}

async def _heartbeat_if_needed(chat_id: Optional[str], notify: Optional[str],
                               min_score: float, found_filtered: bool) -> None:
    global _LAST_GOOD_TS
    hb_hours = float(os.getenv("HEARTBEAT_HOURS", "0") or 0)
    if hb_hours <= 0 or notify != "telegram" or not chat_id:
        return
    now = time.time()
    if found_filtered:
        _LAST_GOOD_TS = now
        return
    if _LAST_GOOD_TS == 0.0:
        _LAST_GOOD_TS = now
        return
    if (now - _LAST_GOOD_TS) >= hb_hours*3600:
        low = float(os.getenv("HEARTBEAT_MIN_SCORE", "4.0"))
        age_min = int((now - _LAST_GOOD_TS)//60)
        txt = (f"בס\"ד\n"
               f"ℹ️ *Heartbeat*: לא נמצאו טריידים שעברו סף {min_score} מזה ~{age_min} ד׳.\n"
               f"נמצאו רק ציונים נמוכים יותר (למשל ~{low}-{max(low,min_score-0.5):.1f}).\n"
               f"_בעזרת השם נעשה ונצליח_ 🙏")
        await telegram_send_markdown(chat_id, txt, None)
        _LAST_GOOD_TS = now

@router.get("/top-volume", summary="Scan with post-filter/notify/ttl/heartbeat + BTC context")
async def scan_top_volume(
    market: str = Query("futures"),
    quote: str = Query("USDT"),
    limit: int = Query(10, ge=1, le=100),
    timeframe: str = Query("15m"),
    kline_limit: int = Query(200, ge=60, le=1000),
    # פוסט־פילטר:
    min_score: float = Query(7.0),
    require_side: bool = Query(True),
    # התראות:
    notify: Optional[str] = Query(None),
    chat_id: Optional[str] = Query(None),
    rich: bool = Query(True),
    ttl_sec: int = Query(900, ge=60, le=86400),
    rearm_score: float = Query(6.0),
    dedupe_window_sec: int = Query(300, ge=0, le=3600),
    # פרמטרים כלכליים:
    leverage: float = Query(float(os.getenv("DEFAULT_LEVERAGE","5"))),
    stake_usdt: float = Query(float(os.getenv("DEFAULT_STAKE_USDT","50"))),
):
    # 1) הבא איתותים גולמיים (החלף במימוש שלך)
    signals_raw: List[Dict[str, Any]] = await _compute_signals(market, quote, limit, timeframe, kline_limit)

    # 2) סינון
    filtered = [s for s in signals_raw if _passes(s, min_score, require_side)]
    notified = 0
    public_host = os.getenv("PUBLIC_HOST", "").strip()

    # 2.5) BTC market context
    btc_ctx = _btc_market_ctx(timeframe)

    # 3) שליחת התראות רק אחרי המסנן
    if notify == "telegram" and chat_id:
        for s in filtered:
            if _should_notify(s, min_score, rearm_score, dedupe_window_sec):
                entry = suggest_entry(s)
                sltp  = compute_sl_tp(s)
                probs = probabilities(s)
                eta   = eta_minutes(s, sltp["R"])
                pnl   = profit_usd(s, sltp, leverage, stake_usdt)
                reason = brief_reason(s)
                payload = {"entry": entry, "sltp": sltp, "probs": probs, "eta": eta, "pnl": pnl, "reason": reason}
                msg = build_trade_message(s, ttl_sec, public_host, leverage, stake_usdt, payload, btc_ctx=btc_ctx)
                await telegram_send_markdown(chat_id, msg["text"], msg["keyboard"])
                notified += 1

    # 4) Heartbeat
    await _heartbeat_if_needed(chat_id, notify, min_score, found_filtered=bool(filtered))

    return {
        "ok": True,
        "count_total": len(signals_raw),
        "returned": len(filtered),
        "notified": notified,
        "signals": filtered,
        "mode": "compact",
        "error": None
    }

@router.get("/now", summary="Alias to /scan/top-volume")
async def scan_now(**kwargs):
    return await scan_top_volume(**kwargs)

# ---- דמו בלבד: החלף למימוש שלך של חישוב איתותים ----
async def _compute_signals(market: str, quote: str, limit: int, timeframe: str, kline_limit: int) -> List[Dict[str, Any]]:
    """
    מימוש הדוגמה מחזיר רשימה ריקה. אצלך יש מחשב איתותים קיים – חבר אותו כאן.
    חובה להחזיר:
    {
      'symbol','timeframe','side' ('BUY'/'SELL' או None),
      'score':float,'note':str,
      'details': {'trend','rsi','adx','ema21','ema50','close','atr'?}
    }
    """
    return []





































