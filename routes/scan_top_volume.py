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

# --- Redis (async) + fallback in-memory ---
from datetime import datetime, timezone, timedelta

try:
    from redis.asyncio import Redis  # type: ignore
except Exception:
    Redis = None  # type: ignore

REDIS_URL = os.getenv("REDIS_URL", "")
_R: Optional["Redis"] = None
_inmem_events: List[float] = []  # fallback (timestamps)
_inmem_lock = False  # פשטני; אין תחרות אמיתית בפרוסס יחיד

def _safe_get_price(symbol: str) -> float:
    try:
        from utils.binance_client import get_price  # type: ignore
        p = get_price(symbol)
        if p:
            return float(p)
    except Exception:
        pass
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

# ============================
# Helpers: env / redis / tune
# ============================

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

async def _redis() -> Optional["Redis"]:
    global _R
    if _R is not None:
        return _R
    if not REDIS_URL or Redis is None:
        return None
    try:
        _R = Redis.from_url(REDIS_URL, health_check_interval=15, client_name="algogpt-autotune")
        return _R
    except Exception as e:
        LOG.warning({"event": "redis.init_failed", "error": str(e)})
        return None

async def _record_trade_event() -> None:
    """
    רושם "טרייד מאושר" לארכיון קצר בחלון זמן (ZSET ב-Redis; fallback רשימה בזיכרון).
    """
    ts = time.time()
    try:
        r = await _redis()
        if r is not None:
            key = "autotune:approved:zset"
            await r.zadd(key, {str(ts): ts})
            # ניקוי ישן מעבר ל-48 שעות כדי לשמור קומפקטיות
            await r.zremrangebyscore(key, 0, ts - 172800)
            return
    except Exception as e:
        LOG.debug({"event": "redis.zadd_failed", "error": str(e)})

    # fallback
    global _inmem_events, _inmem_lock
    while _inmem_lock:
        time.sleep(0.002)
    _inmem_lock = True
    try:
        _inmem_events.append(ts)
        cutoff = ts - 172800
        _inmem_events = [t for t in _inmem_events if t >= cutoff]
    finally:
        _inmem_lock = False

async def _count_trades_in_window(window_min: int) -> int:
    now = time.time()
    start = now - (max(1, window_min) * 60)
    try:
        r = await _redis()
        if r is not None:
            key = "autotune:approved:zset"
            cnt = await r.zcount(key, start, now)
            return int(cnt or 0)
    except Exception as e:
        LOG.debug({"event": "redis.zcount_failed", "error": str(e)})

    # fallback
    global _inmem_events, _inmem_lock
    while _inmem_lock:
        time.sleep(0.002)
    _inmem_lock = True
    try:
        _inmem_events = [t for t in _inmem_events if t >= now - 172800]
        return sum(1 for t in _inmem_events if start <= t <= now)
    finally:
        _inmem_lock = False

def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))

async def _auto_tune_thresholds(base_min_score: float, base_adx_min: float) -> Tuple[float, float, Dict[str, Any]]:
    """
    מכוון דינמית את min_score ואת ADX_MIN לפי קצב טריידים בפועל בחלון זמן נתון.
    מנסה לשמור על TARGET_TRADES_PER_DAY_MIN..MAX.
    """
    if os.getenv("AUTO_TUNE_ENABLE", "1") != "1":
        return base_min_score, base_adx_min, {"enabled": False}

    try:
        # טווחים והגדרות
        lo_score, hi_score = [float(x) for x in (os.getenv("AUTO_MIN_SCORE_RANGE", "6.0,7.5")).split(",")]
        lo_adx, hi_adx = [float(x) for x in (os.getenv("AUTO_ADX_RANGE", "18,25")).split(",")]
    except Exception:
        lo_score, hi_score = 6.0, 7.5
        lo_adx, hi_adx = 18.0, 25.0

    step_score = _get_env_float("AUTO_TUNE_STEP_SCORE", 0.5)    # כמה לשנות בכל איטרציה
    step_adx   = _get_env_float("AUTO_TUNE_STEP_ADX", 1.0)

    win_min    = int(_get_env_float("AUTO_TUNE_LOOKBACK_MIN", 180))
    t_min      = int(_get_env_float("TARGET_TRADES_PER_DAY_MIN", 4))
    t_max      = int(_get_env_float("TARGET_TRADES_PER_DAY_MAX", 10))

    # סופרים כמה טריידים אושרו בחלון
    count = await _count_trades_in_window(win_min)

    # מחשבים "שיעור יומי שקול" לפי יחס חלון→יום
    day_factor = (24*60) / max(1, win_min)
    est_per_day = count * day_factor

    tuned_score = base_min_score
    tuned_adx   = base_adx_min

    if est_per_day < t_min:
        # מעט מדי טריידים → לרכך ספים
        tuned_score = _clamp(base_min_score - step_score, lo_score, hi_score)
        tuned_adx   = _clamp(base_adx_min   - step_adx,   lo_adx,   hi_adx)
    elif est_per_day > t_max:
        # יותר מדי → להקשיח ספים
        tuned_score = _clamp(base_min_score + step_score, lo_score, hi_score)
        tuned_adx   = _clamp(base_adx_min   + step_adx,   lo_adx,   hi_adx)

    meta = {
        "enabled": True,
        "window_min": win_min,
        "events_in_window": count,
        "est_trades_per_day": round(est_per_day, 2),
        "target_range": [t_min, t_max],
        "before": {"min_score": base_min_score, "adx_min": base_adx_min},
        "after":  {"min_score": tuned_score,    "adx_min": tuned_adx},
        "steps": {"score": step_score, "adx": step_adx},
        "ranges": {"score": [lo_score, hi_score], "adx": [lo_adx, hi_adx]},
    }
    return tuned_score, tuned_adx, meta

# ============================
# סינון בסיסי / heartbeat
# ============================

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
    return changed && not recently  # noqa

async def _heartbeat_if_needed(chat_id: Optional[str], notify: Optional[str],
                               min_score: float, found_filtered: bool) -> None:
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

# ============================
# Auto TP/SL (קיים)
# ============================

def _auto_tp_sl(side: Optional[str], close: float, atr_abs: Optional[float], adx: Optional[float]) -> Dict[str, Any]:
    enabled = os.getenv("AUTO_TP_ENABLE", "1") == "1"
    if not enabled or not side or not close or not atr_abs or atr_abs <= 0:
        return {"enabled": False, "sl_price": None, "tp": [], "meta": {"reason": "disabled_or_missing_atr_or_side"}}

    sl_mult = _get_env_float("SL_ATR_MULT_BASE", 1.10)
    tp1_mult = _get_env_float("TP1_ATR_MULT_BASE", 1.20)
    tp2_mult = _get_env_float("TP2_ATR_MULT_BASE", 2.20)
    tp3_mult = _get_env_float("TP3_ATR_MULT_BASE", 3.50)
    tp_mults = [tp1_mult, tp2_mult, tp3_mult]

    adx_min = _get_env_float("ADX_MIN", 20.0)
    adx_boost_thresh = _get_env_float("ADX_TP_BOOST_THRESH", 30.0)
    adx_tp_boost_pct = _get_env_float("ADX_TP_BOOST_PCT", 10.0)
    adx_strong_sl_tighten_pct = _get_env_float("ADX_STRONG_SL_TIGHTEN_PCT", 10.0)
    adx_low_sl_relax_pct = _get_env_float("ADX_LOW_SL_RELAX_PCT", 10.0)
    adx_low_tp_shrink_pct = _get_env_float("ADX_LOW_TP_SHRINK_PCT", 10.0)

    if adx is not None:
        if adx >= adx_boost_thresh:
            sl_mult *= max(0.1, 1.0 - adx_strong_sl_tighten_pct / 100.0)
            tp_mults = [m * (1.0 + adx_tp_boost_pct / 100.0) for m in tp_mults]
        elif adx < adx_min:
            sl_mult *= (1.0 + adx_low_sl_relax_pct / 100.0)
            tp_mults = [m * max(0.1, 1.0 - adx_low_tp_shrink_pct / 100.0) for m in tp_mults]

    sl_dist = max(atr_abs * sl_mult, 1e-9)
    tp_dists = [max(atr_abs * m, 1e-9) for m in tp_mults]

    min_rr = _get_env_float("APPROVAL_RR_MIN", 1.25)
    rr1 = tp_dists[0] / sl_dist if sl_dist > 0 else 0.0
    if rr1 < min_rr:
        scale = min_rr / max(rr1, 1e-9)
        tp_dists = [d * scale for d in tp_dists]
        rr1 = tp_dists[0] / sl_dist

    if side == "BUY":
        sl_price = close - sl_dist
        tp_prices = [close + d for d in tp_dists]
    else:
        sl_price = close + sl_dist
        tp_prices = [close - d for d in tp_dists]

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
            "rr1": float(rr1),
        },
    }

# ============================
# Routes
# ============================

@router.get("/top-volume", summary="Scan (real data only) with post-filter, notify/TTL/heartbeat + auto-tune + auto TP/SL")
async def scan_top_volume(
    market: str = Query("futures"),
    quote: str = Query("USDT"),
    limit: int = Query(10, ge=1, le=100),
    timeframe: str = Query("15m"),
    kline_limit: int = Query(200, ge=60, le=1000),
    min_score: float = Query(0.0),              # יוחלף דינמית אם 0.0 או אם AUTO_TUNE_FORCE=1
    require_side: bool = Query(False),
    notify: Optional[str] = Query(None, description="currently supported: 'telegram'"),
    chat_id: Optional[str] = Query(None),
    rich: bool = Query(True),
    ttl_sec: int = Query(900, ge=60, le=86400),
    rearm_score: float = Query(6.0),
    dedupe_window_sec: int = Query(300, ge=0, le=3600),
    leverage: float = Query(float(os.getenv("DEFAULT_LEVERAGE", "10"))),
    stake_usdt: float = Query(float(os.getenv("DEFAULT_STAKE_USDT", "50"))),
):
    """
    סורק, עושה ניקוד, מטייב דינמית ספים (min_score/ADX), מייצר SL/TP דינמיים, ושולח להצבעה בטלגרם.
    """
    if notify not in _ALLOWED_NOTIFY:
        LOG.warning({"event": "notify.unsupported", "notify": notify})
        notify = None

    # בסיסי מה-env:
    base_min_score = _get_env_float("AUTO_MIN_SCORE_BASE", 7.0)
    base_adx_min   = _get_env_float("AUTO_ADX_MIN_BASE", 20.0)

    # האם לאכוף Auto-Tune גם אם min_score>0?
    force_tune = (os.getenv("AUTO_TUNE_FORCE", "1") == "1")
    want_tune  = (os.getenv("AUTO_TUNE_ENABLE", "1") == "1")

    # קבע ספים אפקטיביים:
    if want_tune and (force_tune or float(min_score or 0.0) <= 0.0):
        eff_min_score, eff_adx_min, tune_meta = await _auto_tune_thresholds(base_min_score, base_adx_min)
    else:
        eff_min_score, eff_adx_min, tune_meta = (float(min_score or base_min_score), base_adx_min, {"enabled": False})

    err: Optional[str] = None
    signals_raw: List[Dict[str, Any]] = []
    try:
        signals_raw = await _compute_signals(market, quote, limit, timeframe, kline_limit, adx_min_override=eff_adx_min)
        if not isinstance(signals_raw, list):
            raise TypeError("signals_raw is not a list")
    except Exception as e:
        err = f"compute_signals_failed: {e}"
        LOG.warning({"event": "scan.compute_failed", "error": str(e)})

    try:
        filtered = [s for s in (signals_raw or []) if isinstance(s, dict) and _passes(s, eff_min_score, require_side)]
    except Exception as e:
        err = f"filter_failed: {e}"
        LOG.warning({"event": "scan.filter_failed", "error": str(e)})
        filtered = []

    LOG.info({
        "event": "scan.result",
        "requested": {"limit": limit, "tf": timeframe, "k": kline_limit, "min_score": min_score, "require_side": require_side},
        "effective": {"min_score": eff_min_score, "adx_min": eff_adx_min, "tune_meta": tune_meta},
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
                # התראות רק מעל סף 7 (למניעת ספאם), אך הסינון לפי eff_min_score כבר קרה
                if _should_notify(s, max(eff_min_score, 7.0), rearm_score, dedupe_window_sec):
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
                            "thresholds": {"min_score": eff_min_score, "adx_min": eff_adx_min},
                            "meta": tune_meta,
                            "tp_sl": {"enabled": bool(prop.get("enabled", False)), "meta": prop.get("meta")},
                        },
                    }
                    idem = f"{(plan['symbol'] or '?')}-{(plan['timeframe'] or timeframe)}-{int(time.time())}"
                    try:
                        await send_trade_approval(idem, plan, chat_id=cid)
                        notified += 1
                        # רושמים "טרייד שאושר" בשביל הלולאת Auto-Tune
                        await _record_trade_event()
                    except Exception as ne:
                        LOG.warning({"event": "notify.send_failed", "symbol": plan.get("symbol"), "error": str(ne)})
            except Exception as loop_e:
                LOG.warning({"event": "notify.loop_failed", "error": str(loop_e)})

    try:
        await _heartbeat_if_needed(chat_id, notify, max(eff_min_score, 7.0), found_filtered=bool(filtered))
    except Exception as hb_e:
        LOG.warning({"event": "heartbeat.failed", "error": str(hb_e)})

    return {
        "ok": err is None,
        "count_total": len(signals_raw or []),
        "returned": len(filtered),
        "notified": notified,
        "signals": filtered if filtered else (signals_raw or []),
        "mode": "full",
        "effective": {"min_score": eff_min_score, "adx_min": eff_adx_min},
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
    leverage: float = Query(float(os.getenv("DEFAULT_LEVERAGE", "10"))),
    stake_usdt: float = Query(float(os.getenv("DEFAULT_STAKE_USDT", "50"))),
    symbol: Optional[str] = Query(None),  # לא בשימוש
):
    return await scan_top_volume(
        market=market, quote=quote, limit=limit, timeframe=timeframe, kline_limit=kline_limit,
        min_score=min_score, require_side=require_side, notify=notify, chat_id=chat_id, rich=rich,
        ttl_sec=ttl_sec, rearm_score=rearm_score, dedupe_window_sec=dedupe_window_sec,
        leverage=leverage, stake_usdt=stake_usdt,
    )

# -------- מחשב איתותים: אמיתי בלבד (אין דמו) + ADX + Auto TP/SL --------
async def _compute_signals(market: str, quote: str, limit: int, timeframe: str, kline_limit: int,
                           adx_min_override: Optional[float] = None) -> List[Dict[str, Any]]:
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
        return (atr / last_close) * 100.0

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
        adx = dx
        return {"adx": adx, "plus_di": plus_di, "minus_di": minus_di}

    wl = os.getenv("WATCHLIST", "BTCUSDT,ETHUSDT,SOLUSDT").split(",")
    wl = [s.strip().upper() for s in wl if s.strip()]
    wl = wl[:max(5, min(limit, 100))]

    tf = timeframe or "15m"
    k = max(60, min(kline_limit, 1000))
    max_atr_pct = _get_env_float("MAX_ATR_PCT", 3.0)
    adx_min = float(adx_min_override if adx_min_override is not None else _get_env_float("ADX_MIN", 20.0))

    if get_klines_sync is None:
        raise RuntimeError("get_klines_sync unavailable")

    for sym in wl:
        try:
            df = get_klines_sync(sym, interval=tf, limit=k)

            closes: List[float]
            raw_rows: Optional[List[List[float]]] = None

            if hasattr(df, "__getitem__") and "close" in getattr(df, "columns", []):
                closes = [float(x) for x in df["close"]]
                if "high" in df.columns and "low" in df.columns:
                    raw_rows = [[None, None, float(h), float(l), float(c)]
                                for h, l, c in zip(df["high"][-k:], df["low"][-k:], df["close"][-k:])]
            elif isinstance(df, list) and len(df) > 0:
                closes = [float(row[4]) for row in df]
                raw_rows = df
            else:
                LOG.debug({"event": "klines.format_unknown", "symbol": sym})
                continue

            if len(closes) < 50:
                continue

            import statistics as _st
            rsi_val = _rsi(closes, 14)
            ema21 = _ema(closes[-100:], 21)
            ema50 = _ema(closes[-200:], 50)
            close = float(closes[-1])

            atr_pct = _atr_pct_from_raw(raw_rows, 14) if raw_rows else None
            adx_pack = _adx_from_raw(raw_rows, 14) if raw_rows else None
            adx = adx_pack["adx"] if adx_pack else None
            plus_di = adx_pack["plus_di"] if adx_pack else None
            minus_di = adx_pack["minus_di"] if adx_pack else None

            side: Optional[str] = None
            if ema21 > ema50 and (rsi_val or 50) >= 48:
                side = "BUY"
            elif ema21 < ema50 and (rsi_val or 50) <= 52:
                side = "SELL"
            if adx is not None and adx < adx_min:
                side = None

            score_1 = 0.0
            if rsi_val is not None:
                score_1 = min(3.5, abs(rsi_val - 50.0) / 10.0 * 3.5)

            score_2_base = 2.0 if side is not None else 0.0
            conf_bonus = 0.0
            if side == "BUY" and rsi_val is not None and rsi_val >= 55 and close > max(ema21, ema50):
                conf_bonus = 0.5 if (plus_di is not None and minus_di is not None and plus_di > minus_di) else 0.3
            elif side == "SELL" and rsi_val is not None and rsi_val <= 45 and close < min(ema21, ema50):
                conf_bonus = 0.5 if (plus_di is not None and minus_di is not None and minus_di > plus_di) else 0.3
            if adx is not None:
                if adx < adx_min:
                    score_2_base *= 0.4
                    conf_bonus = 0.0
                elif adx >= 25:
                    score_2_base *= 1.0
                if adx >= 30:
                    conf_bonus = min(0.5, conf_bonus + 0.1)
            score_2 = min(2.5, score_2_base + conf_bonus)

            score_3 = 0.0
            if ema50 > 0:
                ema_gap_pct = abs(ema21 - ema50) / ema50 * 100.0
                score_3 = min(4.0, ema_gap_pct / 1.2)
                if adx is not None:
                    if adx < adx_min:
                        score_3 *= 0.6
                    elif adx >= 30:
                        score_3 = min(4.0, score_3 * 1.1)

            score_4 = 0.0
            if atr_pct is not None:
                if atr_pct > max_atr_pct:
                    score_4 = -min(3.0, (atr_pct - max_atr_pct) * 0.8)
                elif atr_pct < 0.5:
                    score_4 = -0.3

            raw_total = score_1 + score_2 + score_3 + score_4
            score_total = round(max(0.0, min(raw_total, 10.0)), 2)

            atr_abs = None
            if atr_pct is not None and close > 0:
                atr_abs = (atr_pct / 100.0) * close

            proposal = _auto_tp_sl(side, close, atr_abs, adx)

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
                "side": side,
                "score_total": score_total,
                "components": [
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
                "proposal": proposal,
            })
        except Exception as e:
            LOG.debug({"event": "klines.symbol_failed", "symbol": sym, "error": str(e)})
            continue

    return out
























