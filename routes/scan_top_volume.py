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

# מחיר: קודם utils.binance_client.get_price; אם אין/נכשל — פולבאק ל-python-binance
def _safe_get_price(symbol: str) -> float:
    # 1) utils.binance_client
    try:
        from utils.binance_client import get_price  # type: ignore
        p = get_price(symbol)
        if p:
            return float(p)
    except Exception:
        pass

    # 2) python-binance (אם יש מפתחות)
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

# ערוצי התראה מותרים (להרחבה עתידית)
_ALLOWED_NOTIFY = {"telegram", None}


def _passes(sig: Dict[str, Any], min_score: float, require_side: bool) -> bool:
    try:
        score = float(sig.get("score") or 0)
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
        score = float(sig.get("score") or 0)
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
    לא זורק חריגות — תמיד “כשל בטוח”.
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
    סורק, מסנן לפי min_score/side, שולח אישור טרייד עשיר לטלגרם עם TTL בטקסט,
    + Heartbeat כשאין תוצאות הרבה זמן. תמיד מחזיר JSON (גם בשגיאות פנימיות).
    """
    # אימות ערוץ התראה
    if notify not in _ALLOWED_NOTIFY:
        LOG.warning({"event": "notify.unsupported", "notify": notify})
        notify = None

    # חישוב איתותים (לא מפיל החוצה)
    err: Optional[str] = None
    signals_raw: List[Dict[str, Any]] = []
    try:
        signals_raw = await _compute_signals(market, quote, limit, timeframe, kline_limit)
        if not isinstance(signals_raw, list):
            raise TypeError("signals_raw is not a list")
    except Exception as e:
        err = f"compute_signals_failed: {e}"
        LOG.warning({"event": "scan.compute_failed", "error": str(e)})

    # סינון
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

    # התראות — best-effort
    notified = 0
    if notify == "telegram" and chat_id and filtered:
        try:
            cid = int(chat_id)
        except Exception:
            cid = None

        for s in filtered:
            try:
                if _should_notify(s, min_score, rearm_score, dedupe_window_sec):
                    plan: Dict[str, Any] = {
                        "symbol": s.get("symbol"),
                        "side": s.get("side"),
                        "score": s.get("score"),
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
                    idem = f"{(plan['symbol'] or '?')}-{plan['timeframe']}-{int(time.time())}"
                    try:
                        await send_trade_approval(idem, plan, chat_id=cid)
                        notified += 1
                    except Exception as ne:
                        LOG.warning({"event": "notify.send_failed", "symbol": plan.get("symbol"), "error": str(ne)})
            except Exception as loop_e:
                LOG.warning({"event": "notify.loop_failed", "error": str(loop_e)})

    # Heartbeat
    try:
        await _heartbeat_if_needed(chat_id, notify, min_score, found_filtered=bool(filtered))
    except Exception as hb_e:
        LOG.warning({"event": "heartbeat.failed", "error": str(hb_e)})

    # תמיד נחזיר JSON 200
    return {
        "ok": err is None,
        "count_total": len(signals_raw or []),
        "returned": len(filtered),
        "notified": notified,
        "signals": filtered,
        "mode": "compact",
        "error": err,
    }


@router.get("/now", summary="Alias to /scan/top-volume (safe params)")
async def scan_now(
    market: str = Query("futures"),
    quote: str = Query("USDT"),
    limit: int = Query(10, ge=1, le=100),
    timeframe: str = Query("15m"),
    kline_limit: int = Query(200, ge=60, le=1000),
    min_score: float = Query(7.0),
    require_side: bool = Query(True),
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


# -------- מחשב איתותים: ניסיון אמיתי + fallback דמו --------
async def _compute_signals(market: str, quote: str, limit: int, timeframe: str, kline_limit: int) -> List[Dict[str, Any]]:
    """
    מנסה להביא klines אמיתיים ולחשב RSI/EMA + side/score.
    אם אין דאטה/כשל — מחזיר 1–3 איתותי דמו כדי לאפשר בדיקות/התראות.
    לא זורק חריגות החוצה.
    """
    import statistics, time as _t
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
        rs = avg_gain / avg_loss
        return 100.0 - (100.0 / (1.0 + rs))

    try:
        wl = os.getenv("WATCHLIST", "BTCUSDT,ETHUSDT,SOLUSDT").split(",")
        wl = [s.strip().upper() for s in wl if s.strip()]
        wl = wl[:max(5, min(limit, 20))]

        tf = timeframe or "15m"
        k = max(60, min(kline_limit, 500))

        # ננסה אמיתי; אם לא — ניפול לדמו
        for sym in wl:
            try:
                if get_klines_sync is None:
                    raise RuntimeError("klines unavailable")
                df = get_klines_sync(sym, interval=tf, limit=k)

                if hasattr(df, "__getitem__") and "close" in getattr(df, "columns", []):
                    closes = [float(x) for x in df["close"]]
                elif isinstance(df, list) and len(df) > 0:
                    closes = [float(row[4]) for row in df]
                else:
                    raise RuntimeError("unknown klines format")

                if len(closes) < 20:
                    continue

                rsi_val = _rsi(closes, 14)
                ema21 = statistics.fmean(closes[-21:]) if len(closes) >= 21 else statistics.fmean(closes)
                ema50 = statistics.fmean(closes[-50:]) if len(closes) >= 50 else statistics.fmean(closes[-21:])
                close = float(closes[-1])

                side: Optional[str] = None
                score = 0.0
                trend = "SIDE"
                if rsi_val is not None:
                    if rsi_val <= 32:
                        side = "BUY"; score += (32 - rsi_val) / 2.0
                    elif rsi_val >= 68:
                        side = "SELL"; score += (rsi_val - 68) / 2.0
                if ema21 and ema50:
                    if ema21 > ema50:
                        trend = "UP";  score += 2.5
                    elif ema21 < ema50:
                        trend = "DOWN"; score += 2.5

                score = round(max(0.0, min(score, 10.0)), 2)
                note = f"rsi={rsi_val:.1f} trend={trend}" if rsi_val is not None else f"trend={trend}"
                out.append({
                    "symbol": sym,
                    "timeframe": tf,
                    "side": side,
                    "score": score,
                    "note": note,
                    "details": {"trend": trend, "rsi": rsi_val, "ema21": ema21, "ema50": ema50, "close": close},
                })
            except Exception as e:
                LOG.debug({"event": "klines.symbol_failed", "symbol": sym, "error": str(e)})
                continue

        if out:
            return out

        # --- fallback דמו: יייצר 1–3 איתותים כדי לבדוק Notify/TTL/Heartbeat ---
        now = int(_t.time())
        base = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
        for i, sym in enumerate(base[:max(1, min(3, limit))]):
            phase = (now // 60 + i) % 10
            side = "BUY" if phase < 5 else "SELL"
            score = 7.6 if i == 0 else 6.2 + (i * 0.6)
            price = _safe_get_price(sym)
            out.append({
                "symbol": sym,
                "timeframe": tf,
                "side": side,
                "score": round(score, 2),
                "note": "demo-fallback",
                "details": {"trend": "UP" if side == "BUY" else "DOWN", "rsi": 50.0, "ema21": price, "ema50": price, "close": price},
            })
        return out
    except Exception as e:
        LOG.warning({"event": "compute_signals.crashed", "error": str(e)})
        return []







































