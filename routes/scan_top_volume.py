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


def _get_env_float(key: str, default: float) -> float:
    try:
        return float(os.getenv(key, str(default)))
    except Exception:
        return default


def _parse_splits(env_key: str, default: List[float]) -> List[float]:
    raw = (os.getenv(env_key, "") or "").strip()
    if not raw:
        return default[:]
    try:
        vals = [float(x) for x in raw.split(",") if str(x).strip() != ""]
        s = sum(vals)
        if s <= 0:
            return default[:]
        return [v / s for v in vals]
    except Exception:
        return default[:]


def _auto_tp_sl(side: Optional[str], close: float, atr_abs: Optional[float], adx: Optional[float]) -> Dict[str, Any]:
    """
    מייצר SL/TP דינמיים לפי ATR + ADX + env, תוך שמירה על RR מינימלי.
    מחזיר dict עם sl_price, tp ([{price,fraction},...]), ומטא לשקיפות.
    """
    enabled = os.getenv("AUTO_TP_ENABLE", "1") == "1"
    if not enabled or not side or not close or not atr_abs or atr_abs <= 0:
        return {
            "enabled": False,
            "sl_price": None,
            "tp": [],
            "meta": {"reason": "disabled_or_missing_atr_or_side"}
        }

    # בסיס מה-env:
    sl_mult = _get_env_float("SL_ATR_MULT_BASE", 1.10)
    tp1_mult = _get_env_float("TP1_ATR_MULT_BASE", 1.20)
    tp2_mult = _get_env_float("TP2_ATR_MULT_BASE", 2.20)
    tp3_mult = _get_env_float("TP3_ATR_MULT_BASE", 3.50)
    tp_mults = [tp1_mult, tp2_mult, tp3_mult]

    # ספים/בונוסים לפי ADX:
    adx_min = _get_env_float("ADX_MIN", 20.0)
    adx_boost_thresh = _get_env_float("ADX_TP_BOOST_THRESH", 30.0)
    adx_tp_boost_pct = _get_env_float("ADX_TP_BOOST_PCT", 10.0)   # הגדלת TP כשחזק
    adx_strong_sl_tighten_pct = _get_env_float("ADX_STRONG_SL_TIGHTEN_PCT", 10.0)  # SL קצר יותר כשחזק
    adx_low_sl_relax_pct = _get_env_float("ADX_LOW_SL_RELAX_PCT", 10.0)  # SL רחב יותר כשחלש (אם בכלל נגיע לשם)
    adx_low_tp_shrink_pct = _get_env_float("ADX_LOW_TP_SHRINK_PCT", 10.0)

    # התאמות ADX:
    if adx is not None:
        if adx >= adx_boost_thresh:
            # טרנד חזק => SL מעט מהודק, TP רחוקים יותר
            sl_mult *= max(0.1, 1.0 - adx_strong_sl_tighten_pct / 100.0)
            tp_mults = [m * (1.0 + adx_tp_boost_pct / 100.0) for m in tp_mults]
        elif adx < adx_min:
            # טרנד חלש => אם בכל זאת יש צד, נהיה שמרנים
            sl_mult *= (1.0 + adx_low_sl_relax_pct / 100.0)
            tp_mults = [m * max(0.1, 1.0 - adx_low_tp_shrink_pct / 100.0) for m in tp_mults]

    # מרחקים מוחלטים:
    sl_dist = max(atr_abs * sl_mult, 1e-9)
    tp_dists = [max(atr_abs * m, 1e-9) for m in tp_mults]

    # אכיפת RR מינימלי:
    min_rr = _get_env_float("APPROVAL_RR_MIN", 1.25)
    rr1 = tp_dists[0] / sl_dist if sl_dist > 0 else 0.0
    if rr1 < min_rr:
        scale = min_rr / max(rr1, 1e-9)
        tp_dists = [d * scale for d in tp_dists]
        rr1 = tp_dists[0] / sl_dist

    # בניית מחירים:
    if side == "BUY":
        sl_price = close - sl_dist
        tp_prices = [close + d for d in tp_dists]
    else:  # SELL
        sl_price = close + sl_dist
        tp_prices = [close - d for d in tp_dists]

    # סולם/חלוקה:
    splits = _parse_splits("LADDER_TP_DEFAULT_SPLITS", [0.40, 0.35, 0.25])
    max_ladders = int(float(os.getenv("TP_MAX_LADDERS", "3")))
    tp_prices = tp_prices[:max_ladders]
    splits = (splits + [0.0] * len(tp_prices))[:len(tp_prices)]
    s = sum(splits) or 1.0
    splits = [x / s for x in splits]

    tp_list = [{"price": float(p), "fraction": float(fr)} for p, fr in zip(tp_prices, splits)]

    return {
        "enabled": True,
        "sl_price": float(sl_price),
        "tp": tp_list,
        "meta": {
            "close": float(close),
            "atr_abs": float(atr_abs),
            "sl_dist": float(sl_dist),
            "tp_dists": [float(d) for d in tp_dists],
            "rr1": float(rr1),
            "adx": None if adx is None else float(adx),
            "params": {
                "sl_mult": float(sl_mult),
                "tp_mults": [float(m) for m in tp_mults],
                "min_rr": float(min_rr),
            },
        },
    }


@router.get("/top-volume", summary="Scan (real data only) with post-filter, notify/TTL/heartbeat + auto TP/SL")
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
    סורק ומחזיר *כל* האיתותים (אמיתי בלבד, בלי דמו), עם score_total=1..10 + פירוק components.
    כולל ADX/ATR והצעת TP/SL דינמית לפי env. אם אין דאטה — ok=false ו-error, signals=[].
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
                    det = (s.get("details") or {})
                    prop = (s.get("proposal") or {})
                    plan: Dict[str, Any] = {
                        "symbol": s.get("symbol"),
                        "side": s.get("side"),
                        "score": s.get("score_total"),
                        "timeframe": s.get("timeframe") or timeframe,
                        "order_type": "MARKET",
                        "entry_price": det.get("close"),
                        "sl": {"stopPrice": prop.get("sl_price")},
                        "tp": prop.get("tp") or [],
                        "budget_usd": stake_usdt,
                        "leverage": leverage,
                        "ttl_sec": ttl_sec,
                        "why": s.get("note") or det.get("trend") or "—",
                        "rich": bool(rich),
                        "auto_tune": {
                            "enabled": bool(prop.get("enabled", False)),
                            "meta": prop.get("meta"),
                        },
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


# -------- מחשב איתותים: אמיתי בלבד (אין fallback דמו) + ADX + Auto TP/SL --------
async def _compute_signals(market: str, quote: str, limit: int, timeframe: str, kline_limit: int) -> List[Dict[str, Any]]:
    """
    מביא klines אמיתיים ומחשב score_total=1..10 + פירוק components.
    גרסת Trend-Aggressive + ADX + Auto TP/SL:
    - משקל גבוה ל-EMA gap, ענישת ATR קשיחה יותר
    - אכיפת ADX_MIN לכיוון/ציון
    - הצעת SL/TP לפי ATR/ADX עם אכיפת RR מינימלי
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
        for i in range(1, period + 1):
            ch = closes[-i] - closes[-i-1]
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
        return (atr / last_close) * 100.0  # באחוזים

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

        # לשם איתות מיידי: Wilder smoothing בקירוב ממוצע
        def _wilder_smooth(seq: List[float]) -> float:
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
        adx = dx  # הערכה מיידית (ללא EMA על DX)
        return {"adx": adx, "plus_di": plus_di, "minus_di": minus_di}

    # universe
    wl = os.getenv("WATCHLIST", "BTCUSDT,ETHUSDT,SOLUSDT").split(",")
    wl = [s.strip().upper() for s in wl if s.strip()]
    wl = wl[:max(5, min(limit, 100))]

    tf = timeframe or "15m"
    k = max(60, min(kline_limit, 1000))
    max_atr_pct = _get_env_float("MAX_ATR_PCT", 3.0)
    adx_min = _get_env_float("ADX_MIN", 20.0)

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
            if adx is not None and adx < adx_min:
                side = None  # טרנד חלש מדי — לא נכריז על צד

            # ===== ניקוד רכיבים (1/2/3/4) =====
            # 1) RSI distance סביב 50: עד 3.5 נק'
            score_1 = 0.0
            if rsi_val is not None:
                score_1 = min(3.5, abs(rsi_val - 50.0) / 10.0 * 3.5)

            # 2) EMA trend + bonus יישור (עד 2.5 נק'):
            score_2_base = 2.0 if side is not None else 0.0
            conf_bonus = 0.0
            if side == "BUY" and rsi_val is not None and rsi_val >= 55 and close > max(ema21, ema50):
                if plus_di is not None and minus_di is not None and plus_di > minus_di:
                    conf_bonus = 0.5
                else:
                    conf_bonus = 0.3
            elif side == "SELL" and rsi_val is not None and rsi_val <= 45 and close < min(ema21, ema50):
                if plus_di is not None and minus_di is not None and minus_di > plus_di:
                    conf_bonus = 0.5
                else:
                    conf_bonus = 0.3
            if adx is not None:
                if adx < adx_min:
                    score_2_base *= 0.4
                    conf_bonus = 0.0
                elif adx >= 25:
                    score_2_base *= 1.0
                if adx >= 30:
                    conf_bonus = min(0.5, conf_bonus + 0.1)
            score_2 = min(2.5, score_2_base + conf_bonus)

            # 3) EMA gap pct (עד 4 נק') — טרנד-אגרסיבי, scaling לפי ADX:
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

            # ATR מוחלט (להצעת SL/TP):
            atr_abs = None
            if atr_pct is not None and close > 0:
                atr_abs = (atr_pct / 100.0) * close

            # Auto-Tune TP/SL (אם יש SIDE + ATR):
            proposal = _auto_tp_sl(side, close, atr_abs, adx)

            # תיאור (note)
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
                    "atr_pct": atr_pct, "atr_abs": atr_abs,
                    "adx": adx, "plus_di": plus_di, "minus_di": minus_di
                },
                "proposal": proposal,   # <<=== כאן ה-SL/TP המוצע
            })
        except Exception as e:
            LOG.debug({"event": "klines.symbol_failed", "symbol": sym, "error": str(e)})
            continue

    return out



























