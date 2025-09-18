# routes/scan_top_volume.py
from __future__ import annotations

import os
import time
from typing import Optional, Dict, Any, List

from fastapi import APIRouter, Query, Depends

# --- auth (fallback בטוח) ---
try:
    from utils.auth import require_bearer_token  # type: ignore
except Exception:
    def require_bearer_token():
        return None

# --- notifier: נשתמש בשליחת אישור טרייד העשירה שכבר ב-telegram_notifier ---
try:
    from utils.telegram_notifier import send_trade_approval
except Exception:
    async def send_trade_approval(idem: str, plan: Dict[str, Any], chat_id: Optional[int] = None) -> None:
        return None

# לשליחת טקסט פשוט (ל-Heartbeat)
try:
    from utils.telegram_notifier_core import _tg_send as _tg_send_text
except Exception:
    async def _tg_send_text(text: str, chat_id: Optional[int] = None) -> None:
        return None

# נתוני שוק BTC (אופציונלי, לא חובה פה כי send_trade_approval כבר מוסיף הקשר)
try:
    from utils.get_klines import get_klines_sync  # warmup קיים ב-startup
except Exception:
    get_klines_sync = None

try:
    from utils.binance_client import get_price
except Exception:
    def get_price(symbol: str) -> float:  # type: ignore
        return 0.0

router = APIRouter(prefix="/scan", tags=["Scanner"], dependencies=[Depends(require_bearer_token)])

# --- זיכרון קטן למניעת ספאם (arm/disarm) ---
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
    st = _STATE.get(key) or {"state": "disarmed", "last_ts": 0.0, "last_score": 0.0}
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
    st["last_ts"] = now
    st["last_score"] = score
    _STATE[key] = st
    return changed and not recently


async def _heartbeat_if_needed(chat_id: Optional[str], notify: Optional[str],
                               min_score: float, found_filtered: bool) -> None:
    """
    שולח Heartbeat אם לא נמצאו טריידים מעל הסף במשך HEARTBEAT_HOURS.
    """
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
    if (now - _LAST_GOOD_TS) >= hb_hours * 3600:
        low = float(os.getenv("HEARTBEAT_MIN_SCORE", "4.0"))
        age_min = int((now - _LAST_GOOD_TS) // 60)
        txt = (
            'בס"ד\n'
            f"ℹ️ *Heartbeat*: לא נמצאו טריידים שעברו סף {min_score} מזה ~{age_min} ד׳.\n"
            f"נמצאו רק ציונים נמוכים יותר (למשל ~{low}-{max(low, min_score - 0.5):.1f}).\n"
            "_בעזרת השם נעשה ונצליח_ 🙏"
        )
        # _tg_send_text תומך ב-HTML; פה שולחים טקסט רגיל – זה בסדר.
        try:
            cid = int(chat_id)
        except Exception:
            cid = None
        await _tg_send_text(txt, chat_id=cid)
        _LAST_GOOD_TS = now


@router.get("/top-volume", summary="Scan with post-filter, notify/TTL/heartbeat")
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
    # פרמטרים כלכליים (ברירת מחדל מה-ENV):
    leverage: float = Query(float(os.getenv("DEFAULT_LEVERAGE", "5"))),
    stake_usdt: float = Query(float(os.getenv("DEFAULT_STAKE_USDT", "50"))),
):
    """
    סורק, מסנן לפי min_score ו-side, ושולח הודעת אישור עשירה בטלגרם (עם TTL בטקסט),
    רק על מה שעבר את הסינון. בנוסף Heartbeat אם אין תוצאות לאורך זמן.
    """
    signals_raw: List[Dict[str, Any]] = await _compute_signals(market, quote, limit, timeframe, kline_limit)

    # מסנן תוצאות
    filtered = [s for s in signals_raw if _passes(s, min_score, require_side)]

    notified = 0
    # שולח רק אחרי המסנן
    if notify == "telegram" and chat_id:
        try:
            cid = int(chat_id)
        except Exception:
            cid = None
        for s in filtered:
            if _should_notify(s, min_score, rearm_score, dedupe_window_sec):
                # מרכיבים plan מינימלי לשליחה, וה-notifier משלים הערכות/שוק/ETA/הסתברויות
                plan: Dict[str, Any] = {
                    "symbol": s.get("symbol"),
                    "side": s.get("side"),
                    "score": s.get("score"),
                    "timeframe": s.get("timeframe") or timeframe,
                    "order_type": "MARKET",
                    "entry_price": s.get("details", {}).get("close"),  # best-effort
                    "sl": {"stopPrice": None},                         # יחושב אצלך/ב-estimation אם יש
                    "tp": [],                                          # idem
                    "budget_usd": stake_usdt,
                    "leverage": leverage,
                    "ttl_sec": ttl_sec,
                    "why": s.get("note") or s.get("details", {}).get("trend") or "—",
                }
                idem = f"{plan['symbol']}-{plan['timeframe']}-{int(time.time())}"
                await send_trade_approval(idem, plan, chat_id=cid)
                notified += 1

    # Heartbeat אם צריך
    await _heartbeat_if_needed(chat_id, notify, min_score, found_filtered=bool(filtered))

    return {
        "ok": True,
        "count_total": len(signals_raw),
        "returned": len(filtered),
        "notified": notified,
        "signals": filtered,
        "mode": "compact",
        "error": None,
    }


@router.get("/now", summary="Alias to /scan/top-volume")
async def scan_now(**kwargs):
    return await scan_top_volume(**kwargs)


# -------- החלף למחשב האיתותים האמיתי שלך --------
async def _compute_signals(market: str, quote: str, limit: int, timeframe: str, kline_limit: int) -> List[Dict[str, Any]]:
    """
    דמו: תחזיר רשימה ריקה. חבר פה את מחשב האיתותים האמיתי שלך.
    על כל איתות נדרש:
      {
        'symbol': 'ETHUSDT',
        'timeframe': '15m',
        'side': 'BUY'/'SELL' או None,
        'score': float,
        'note': str,
        'details': {
            'trend': 'UP/DOWN/SIDE',
            'rsi': float,
            'adx': float,
            'ema21': float,
            'ema50': float,
            'close': float,
            'atr': float (אופציונלי)
        }
      }
    """
    return []






































