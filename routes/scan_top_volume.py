# routes/scan_top_volume.py
from __future__ import annotations

import os
import time
import logging
from typing import Optional, Dict, Any, List, Tuple

from fastapi import APIRouter, Query, Depends

LOG = logging.getLogger("algogpt.scan")

# --- auth (fallback בטוח) ---
try:
    from utils.auth import require_bearer_token  # type: ignore
except Exception:
    def require_bearer_token():
        return None

# --- notifier: שליחת "אישור טרייד" עשירה לטלגרם ---
try:
    from utils.telegram_notifier import send_trade_approval  # type: ignore
except Exception:
    async def send_trade_approval(idem: str, plan: Dict[str, Any], chat_id: Optional[int] = None) -> None:
        return None

# --- טקסט פשוט (Heartbeat/בדיקות) ---
try:
    from utils.telegram_notifier_core import _tg_send as _tg_send_text  # type: ignore
except Exception:
    async def _tg_send_text(text: str, chat_id: Optional[int] = None) -> None:
        return None

# --- דאטה שוק (klines/price) ---
try:
    from utils.get_klines import get_klines_sync  # type: ignore
except Exception:
    get_klines_sync = None  # type: ignore


def _safe_get_price(symbol: str) -> float:
    # 1) utils.binance_client
    try:
        from utils.binance_client import get_price  # type: ignore
        p = get_price(symbol)
        if p:
            return float(p)
    except Exception:
        pass
    # 2) python-binance futures ticker (אם יש מפתחות)
    try:
        from binance.client import Client  # type: ignore
        api_key = os.getenv("BINANCE_API_KEY", "").strip()
        api_sec = os.getenv("BINANCE_API_SECRET", "").strip()
        if not api_key or not api_sec:
            return 0.0
        cli = Client(api_key, api_sec)
        info = cli.futures_symbol_ticker(symbol=str(symbol).upper())
        if info and "price" in info:
            return float(info["price"])
    except Exception as e:
        LOG.debug({"event": "price.fallback_failed", "symbol": symbol, "error": str(e)})
    return 0.0


router = APIRouter(prefix="/scan", tags=["scan"], dependencies=[Depends(require_bearer_token)])

# --- זיכרון קטן למניעת ספאם (per symbol+timeframe) ---
_STATE: Dict[Tuple[str, str], Dict[str, Any]] = {}
_LAST_GOOD_TS = 0.0
_ALLOWED_NOTIFY = {"telegram", None}


def _passes(sig: Dict[str, Any], min_score: float, require_side: bool) -> bool:
    try:
        score = float(sig.get("score_total") or sig.get("score") or 0)
    except Exception:
        score = 0.0
    side = (sig.get("side") or "").upper()
    return (score >= float(min_score or 0)) and ((not require_side) or (side in ("BUY", "SELL")))


def _should_notify(sig: Dict[str, Any], min_score: float, rearm_score: float, dedupe_window_sec: int) -> bool:
    symbol = str(sig.get("symbol") or "").upper() or "?"
    timeframe = str(sig.get("timeframe") or "").lower() or "?"
    key = (symbol, timeframe)

    now = time.time()
    st = _STATE.get(key) or {"state": "disarmed", "last_ts": 0.0, "last_score": 0.0}
    try:
        score = float(sig.get("score_total") or sig.get("score") or 0)
    except Exception:
        score = 0.0

    changed = False
    if st["state"] == "disarmed":
        if score >= min_score:
            st["state"] = "armed"
            changed = True
    else:
        if score < rearm_score:
            st["state"] = "disarmed"

    recently = (now - float(st.get("last_ts") or 0.0)) < max(0, int(dedupe_window_sec or 0))
    st["last_ts"] = now
    st["last_score"] = score
    _STATE[key] = st
    return changed and not recently


async def _heartbeat_if_needed(chat_id: Optional[str], notify: Optional[str],
                               min_score: float, found_filtered: bool) -> None:
    """
    שולח Heartbeat אם לא נמצאו טריידים מעל הסף במשך HEARTBEAT_HOURS.
    לא זורק חריגות — “כשל בטוח”.
    """
    global _LAST_GOOD_TS
    try:
        hb_hours = float(os.getenv("HEARTBEAT_HOURS", "0") or 0)
    except Exception:
        hb_hours = 0.0

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
        try:
            low = float(os.getenv("HEARTBEAT_MIN_SCORE", "4.0"))
        except Exception:
            low = 4.0

        age_min = int((now - _LAST_GOOD_TS) // 60)
        txt = (
            'בס"ד\n'
            f"ℹ️ Heartbeat: לא נמצאו טריידים ≥ {min_score} מזה ~{age_min} ד׳.\n"
            f"נרשמו רק ציונים נמוכים יותר (למשל ~{low}-{max(low, min_score - 0.5):.1f}).\n"
            "_בעזרת השם נעשה ונצליח_ 🙏"
        )
        try:
            cid = int(chat_id)
        except Exception:
            cid = None

        try:
            await _tg_send_text(txt, chat_id=cid)
        except Exception as e:
            LOG.warning({"event": "heartbeat.send_failed", "error": str(e)})
        finally:
            _LAST_GOOD_TS = now


@router.get("/top-volume", summary="Scan (real data only) with post-filter, notify/TTL/heartbeat")
async def scan_top_volume(
    market: str = Query("futures"),
    quote: str = Query("USDT"),
    limit: int = Query(10, ge=1, le=100),
    timeframe: str = Query("15m"),
    kline_limit: int = Query(200, ge=60, le=1000),
    # פוסט־פילטר — ברירת מחדל: כל האיתותים
    min_score: float = Query(0.0),
    require_side: bool = Query(False),
    # התראות:
    notify: Optional[str] = Query(None, description="currently supported: 'telegram'"),
    chat_id: Optional[str] = Query(None),
    rich: bool = Query(True),
    ttl_sec: int = Query(900, ge=60, le=86400),
    rearm_score: float = Query(6.0),
    dedupe_window_sec: int = Query(300, ge=0, le=3600),
    # כלכלה:
    leverage: float = Query(float(os.getenv("DEFAULT_LEVERAGE", "5"))),
    stake_usdt: float = Query(float(os.getenv("DEFAULT_STAKE_USDT", "50"))),
):
    """
    סורק ומחזיר *כל* האיתותים (אמיתי בלבד, בלי דמו), עם score_total=1..10 + פירוק components (ציון 1/2/3/4).
    אם אין דאטה — ok=false ו-error, signals=[]
    """
    if notify not in _ALLOWED_NOTIFY:
        LOG.warning({"event": "notify.unsupported", "notify": notify})
        notify = None

    err: Optional[str] = None
    signals_raw: List[Dict[str, Any]] = []
    try:
        signals_raw = await _compute_signals(market, quote, limit, timeframe, kline_limit)
        if not isinstance(signals_raw, list):
            raise TypeError("signals_raw is not a list")
    except Exception as e:
        err = f"compute_signals_failed: {e}"
        LOG.warning({"event": "scan.compute_failed", "error": str(e)})

    try:
        filtered = [s for s in (signals_raw or []) if isinstance(s, dict) and _passes(s, min_score, require_side)]
    except Exception as e:
        err = f"filter_failed: {e}"
        LOG.warning({"event": "scan.filter_failed", "error": str(e)})
        filtered = []

    LOG.info({
        "event": "scan.result",
        "requested": {"limit": limit, "tf": timeframe, "k": kline_limit, "min_score": min_score, "require_side": require_side},
        "counts": {"total": len(signals_raw or []), "returned": len(filtered)},
    })

    notified = 0
    if notify == "telegram" and chat_id and filtered:
        try:
            cid = int(chat_id)
        except Exception:
            cid = None
        for s in filtered:
            try:
                if _should_notify(s, max(min_score, 7.0), rearm_score, dedupe_window_sec):
                    plan: Dict[str, Any] = {
                        "symbol": s.get("symbol"),
                        "side": s.get("side"),
                        "score": s.get("score_total"),
                        "timeframe": s.get("timeframe") or timeframe,
                        "order_type": "MARKET",
                        "entry_price": (s.get("details", {}) or {}).get("close"),
                        "sl": {"stopPrice": None},
                        "tp": [],
                        "budget_usd": stake_usdt,
                        "leverage": leverage,
                        "ttl_sec": ttl_sec,
                        "why": s.get("note") or (s.get("details", {}) or {}).get("trend") or "—",
                        "rich": bool(rich),
                    }
                    idem = f"{(plan['symbol'] or '?')}-{(plan['timeframe'] or timeframe)}-{int(time.time())}"
                    try:
                        await send_trade_approval(idem, plan, chat_id=cid)
                        notified += 1
                    except Exception as ne:
                        LOG.warning({"event": "notify.send_failed", "symbol": plan.get("symbol"), "error": str(ne)})
            except Exception as loop_e:
                LOG.warning({"event": "notify.loop_failed", "error": str(loop_e)})

    try:
        await _heartbeat_if_needed(chat_id, notify, max(min_score, 7.0), found_filtered=bool(filtered))
    except Exception as hb_e:
        LOG.warning({"event": "heartbeat.failed", "error": str(hb_e)})

    return {
        "ok": err is None,
        "count_total": len(signals_raw or []),
        "returned": len(filtered),
        "notified": notified,
        "signals": filtered if filtered else (signals_raw or []),
        "mode": "full",
        "error": err,
    }


@router.get("/now", summary="Alias to /scan/top-volume (real data only)")
async def scan_now(
    market: str = Query("futures"),
    quote: str = Query("USDT"),
    limit: int = Query(10, ge=1, le=100),
    timeframe: str = Query("15m"),
    kline_limit: int = Query(200, ge=60, le=1000),
    min_score: float = Query(0.0),
    require_side: bool = Query(False),
    notify: Optional[str] = Query(None),
    chat_id: Optional[str] = Query(None),
    rich: bool = Query(True),
    ttl_sec: int = Query(900, ge=60, le=86400),
    rearm_score: float = Query(6.0),
    dedupe_window_sec: int = Query(300, ge=0, le=3600),
    leverage: float = Query(float(os.getenv("DEFAULT_LEVERAGE", "5"))),
    stake_usdt: float = Query(float(os.getenv("DEFAULT_STAKE_USDT", "50"))),
    symbol: Optional[str] = Query(None),  # תאימות לאחור; לא בשימוש
):
    return await scan_top_volume(
        market=market,
        quote=quote,
        limit=limit,
        timeframe=timeframe,
        kline_limit=kline_limit,
        min_score=min_score,
        require_side=require_side,
        notify=notify,
        chat_id=chat_id,
        rich=rich,
        ttl_sec=ttl_sec,
        rearm_score=rearm_score,
        dedupe_window_sec=dedupe_window_sec,
        leverage=leverage,
        stake_usdt=stake_usdt,
    )


# -------- מחשב איתותים: אמיתי בלבד (אין fallback דמו) + ADX --------
async def _compute_signals(market: str, quote: str, limit: int, timeframe: str, kline_limit: int) -> List[Dict[str, Any]]:
    """
    מביא klines אמיתיים ומחשב score_total=1..10 + פירוק components.
    גרסה Trend-Aggressive עם ADX: משקל גבוה ל-EMA gap, ענישת ATR קשיחה יותר,
    ואכיפת סף ADX_MIN על הכיוון/ציון.
    """
    import statistics
    out: List[Dict[str, Any]] = []

    def _rsi(closes: List[float], period: int = 14) -> Optional[float]:
        if len(closes) < period + 1:
            return None
        gains, losses = [], []
        for i in range(1, period + 1):
            ch = closes[-i] - closes[-i-1]
            gains.append(max(ch, 0.0))
            losses.append(abs(min(ch, 0.0)))
        avg_gain = statistics.fmean(gains) if any(gains) else 0.0
        avg_loss = statistics.fmean(losses) if any(losses) else 0.0
        if avg_loss == 0:
            return 100.0
        rs = avg_gain / (avg_loss or 1e-9)
        return 100.0 - (100.0 / (1.0 + rs))

    def _ema(seq: List[float], n: int) -> float:
        if not seq:
            return 0.0
        k = 2 / (n + 1)
        ema = seq[0]
        for v in seq[1:]:
            ema = v * k + ema * (1 - k)
        return ema

    def _atr_pct_from_raw(rows: List[List[float]], period: int = 14) -> Optional[float]:
        if len(rows) < period + 1:
            return None
        trs = []
        prev_close = float(rows[-period-1][4])
        for r in rows[-period:]:
            h = float(r[2]); l = float(r[3]); c = float(r[4])
            tr = max(h - l, abs(h - prev_close), abs(l - prev_close))
            trs.append(tr)
            prev_close = c
        atr = statistics.fmean(trs)
        last_close = float(rows[-1][4])
        if last_close <= 0:
            return None
        return (atr / last_close) * 100.0  # אחוז

    # Wilder's ADX (+DI/-DI)
    def _adx_from_raw(rows: List[List[float]], period: int = 14) -> Optional[Dict[str, float]]:
        if len(rows) < period + 2:
            return None
        trs, dm_plus, dm_minus = [], [], []
        for i in range(1, period + 1):
            h1, l1, c1 = float(rows[-i][2]), float(rows[-i][3]), float(rows[-i][4])
            h0, l0, c0 = float(rows[-i-1][2]), float(rows[-i-1][3]), float(rows[-i-1][4])
            up = h1 - h0
            dn = l0 - l1
            dm_plus.append(up if (up > dn and up > 0) else 0.0)
            dm_minus.append(dn if (dn > up and dn > 0) else 0.0)
            tr = max(h1 - l1, abs(h1 - c0), abs(l1 - c0))
            trs.append(tr)

        # Wilder smoothing
        import math
        def _wilder_smooth(seq: List[float]) -> float:
            # לשם איתות מיידי: ניקח ממוצע פשוט; בעיבוד מלא נעשה ריצה על כל הסדרה
            return statistics.fmean(seq) if seq else 0.0

        tr14 = _wilder_smooth(trs)
        plus_dm14 = _wilder_smooth(dm_plus)
        minus_dm14 = _wilder_smooth(dm_minus)
        if tr14 <= 0:
            return None
        plus_di = 100.0 * (plus_dm14 / tr14)
        minus_di = 100.0 * (minus_dm14 / tr14)
        diff = abs(plus_di - minus_di)
        summ = plus_di + minus_di if (plus_di + minus_di) != 0 else 1e-9
        dx = 100.0 * (diff / summ)
        adx = dx  # הערכה מיידית; (ללא ריצה מתגלגלת)
        return {"adx": adx, "plus_di": plus_di, "minus_di": minus_di}

    # universe
    wl = os.getenv("WATCHLIST", "BTCUSDT,ETHUSDT,SOLUSDT").split(",")
    wl = [s.strip().upper() for s in wl if s.strip()]
    wl = wl[:max(5, min(limit, 100))]

    tf = timeframe or "15m"
    k = max(60, min(kline_limit, 1000))
    max_atr_pct = float(os.getenv("MAX_ATR_PCT", "3"))
    adx_min = float(os.getenv("ADX_MIN", "20"))

    if get_klines_sync is None:
        raise RuntimeError("get_klines_sync unavailable")

    for sym in wl:
        try:
            df = get_klines_sync(sym, interval=tf, limit=k)

            closes: List[float]
            raw_rows: Optional[List[List[float]]] = None

            # DataFrame
            if hasattr(df, "__getitem__") and "close" in getattr(df, "columns", []):
                closes = [float(x) for x in df["close"]]
                if "high" in df.columns and "low" in df.columns:
                    raw_rows = [[None, None, float(h), float(l), float(c)]
                                for h, l, c in zip(df["high"][-k:], df["low"][-k:], df["close"][-k:])]
            # List[List]
            elif isinstance(df, list) and len(df) > 0:
                closes = [float(row[4]) for row in df]
                raw_rows = df
            else:
                LOG.debug({"event": "klines.format_unknown", "symbol": sym})
                continue

            if len(closes) < 50:
                continue

            rsi_val = _rsi(closes, 14)
            ema21 = _ema(closes[-100:], 21)
            ema50 = _ema(closes[-200:], 50)
            close = float(closes[-1])

            atr_pct = _atr_pct_from_raw(raw_rows, 14) if raw_rows else None
            adx_pack = _adx_from_raw(raw_rows, 14) if raw_rows else None
            adx = adx_pack["adx"] if adx_pack else None
            plus_di = adx_pack["plus_di"] if adx_pack else None
            minus_di = adx_pack["minus_di"] if adx_pack else None

            # SIDE בסיסית + אכיפת ADX_MIN:
            side: Optional[str] = None
            if ema21 > ema50 and (rsi_val or 50) >= 48:
                side = "BUY"
            elif ema21 < ema50 and (rsi_val or 50) <= 52:
                side = "SELL"
            # אם ADX נמוך מדי — מבטלים כיוון (זהירות) כדי לא “לצבוע” טרייד בכוח
            if adx is not None and adx < adx_min:
                side = None

            # ===== ניקוד רכיבים (1/2/3/4) =====
            # 1) RSI distance סביב 50: עד 3.5 נק'
            score_1 = 0.0
            if rsi_val is not None:
                score_1 = min(3.5, abs(rsi_val - 50.0) / 10.0 * 3.5)

            # 2) EMA trend + bonus יישור (עד 2.5 נק'):
            score_2_base = 2.0 if side is not None else 0.0
            conf_bonus = 0.0
            if side == "BUY" and rsi_val is not None and rsi_val >= 55 and close > max(ema21, ema50):
                # בונוס נוסף אם +DI בולט:
                if plus_di is not None and minus_di is not None and plus_di > minus_di:
                    conf_bonus = 0.5
                else:
                    conf_bonus = 0.3
            elif side == "SELL" and rsi_val is not None and rsi_val <= 45 and close < min(ema21, ema50):
                if plus_di is not None and minus_di is not None and minus_di > plus_di:
                    conf_bonus = 0.5
                else:
                    conf_bonus = 0.3
            # דיכוי/עידוד ע"י ADX (רק בתוך הרכיב הזה כדי לשמור 1..4):
            if adx is not None:
                if adx < adx_min:
                    score_2_base *= 0.4  # טרנד חלש => נחתוך השפעת המגמה
                    conf_bonus = 0.0
                elif adx >= 25:
                    score_2_base *= 1.0
                if adx >= 30:
                    conf_bonus = min(0.5, conf_bonus + 0.1)

            score_2 = min(2.5, score_2_base + conf_bonus)

            # 3) EMA gap pct (עד 4 נק') — טרנד-אגרסיבי, עם scaling לפי ADX:
            score_3 = 0.0
            if ema50 > 0:
                ema_gap_pct = abs(ema21 - ema50) / ema50 * 100.0
                score_3 = min(4.0, ema_gap_pct / 1.2)  # 1.2% => נק' אחת
                if adx is not None:
                    if adx < adx_min:
                        score_3 *= 0.6
                    elif adx >= 30:
                        score_3 = min(4.0, score_3 * 1.1)

            # 4) ענישת ATR% (שלילי), קשיחה יותר; ואופציה לקצה תחתון "שוק מת"
            score_4 = 0.0
            if atr_pct is not None:
                if atr_pct > max_atr_pct:
                    score_4 = -min(3.0, (atr_pct - max_atr_pct) * 0.8)  # קשיח עד -3
                elif atr_pct < 0.5:
                    score_4 = -0.3  # רעש נמוך מדי

            # סכימה וסופית לתחום [0..10]
            raw_total = score_1 + score_2 + score_3 + score_4
            score_total = round(max(0.0, min(raw_total, 10.0)), 2)

            # תיאור
            note_parts = []
            if rsi_val is not None:
                note_parts.append(f"rsi={rsi_val:.1f}")
            note_parts.append("ema21>ema50" if ema21 > ema50 else ("ema21<ema50" if ema21 < ema50 else "ema21≈ema50"))
            if atr_pct is not None:
                note_parts.append(f"atr%={atr_pct:.2f}")
            if adx is not None:
                note_parts.append(f"adx={adx:.1f}")
            note = " ".join(note_parts)

            out.append({
                "symbol": sym,
                "timeframe": tf,
                "side": side,                         # "BUY"/"SELL"/None
                "score_total": score_total,           # 1..10 (מנורמל)
                "components": [                       # “ציון 1/2/3/4”
                    {"id": 1, "name": "rsi_distance", "score": round(score_1, 2)},
                    {"id": 2, "name": "ema_trend",    "score": round(score_2, 2),
                     "extras": {"confirmation_bonus": round(conf_bonus, 2)}},
                    {"id": 3, "name": "ema_gap_pct",  "score": round(score_3, 2)},
                    {"id": 4, "name": "atr_penalty",  "score": round(score_4, 2)},
                ],
                "note": note,
                "details": {
                    "trend": "UP" if ema21 > ema50 else ("DOWN" if ema21 < ema50 else "FLAT"),
                    "rsi": rsi_val, "ema21": ema21, "ema50": ema50, "close": close,
                    "atr_pct": atr_pct, "adx": adx, "plus_di": plus_di, "minus_di": minus_di
                },
            })
        except Exception as e:
            LOG.debug({"event": "klines.symbol_failed", "symbol": sym, "error": str(e)})
            continue

    return out































