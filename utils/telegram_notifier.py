# utils/telegram_notifier.py
from __future__ import annotations
import os, time, asyncio, logging
from typing import List, Dict, Any, Optional

try:
    import httpx
except Exception:
    httpx = None  # type: ignore

logger = logging.getLogger("algogpt.telegram")

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
CHAT_ID   = int(os.getenv("TELEGRAM_CHAT_ID", "0") or "0")

# ---- Explain Trade flags / throttling ----
OPS_EXPLAIN_TRADE_TELEGRAM = os.getenv("OPS_EXPLAIN_TRADE_TELEGRAM", "1").lower() in ("1","true","yes","on")
OPS_EXPLAIN_COOLDOWN_SEC   = int(os.getenv("OPS_EXPLAIN_COOLDOWN_SEC", "45"))
OPS_EXPLAIN_MAX_PER_MIN    = int(os.getenv("OPS_EXPLAIN_MAX_PER_MIN", "6"))
OPS_EXPLAIN_BATCH          = os.getenv("OPS_EXPLAIN_BATCH", "1").lower() in ("1","true","yes","on")

# Simple throttling state
_last_explain_ts: float = 0.0
_window_start_ts: float = 0.0
_sent_in_window: int = 0

API_BASE = f"https://api.telegram.org/bot{BOT_TOKEN}" if BOT_TOKEN else ""

def _tg_enabled() -> bool:
    return bool(BOT_TOKEN and CHAT_ID and httpx is not None)

async def _tg_send(text: str) -> None:
    """Tiny retry wrapper for Telegram sendMessage."""
    if not _tg_enabled():
        return
    for attempt in range(1, 4):
        try:
            async with httpx.AsyncClient(timeout=10.0) as cli:  # type: ignore
                await cli.post(
                    f"{API_BASE}/sendMessage",
                    data={"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True},
                )
            return
        except Exception as e:
            if attempt == 3:
                logger.warning("telegram send failed (final): %s", e)
            else:
                await asyncio.sleep(0.6 * attempt)

def _should_send_explain(now: float) -> bool:
    global _last_explain_ts, _window_start_ts, _sent_in_window
    # cooldown gate
    if (now - _last_explain_ts) < max(0, OPS_EXPLAIN_COOLDOWN_SEC):
        return False
    # per-minute window gate
    if _window_start_ts == 0.0 or (now - _window_start_ts) >= 60.0:
        _window_start_ts = now
        _sent_in_window = 0
    if OPS_EXPLAIN_MAX_PER_MIN > 0 and _sent_in_window >= OPS_EXPLAIN_MAX_PER_MIN:
        return False
    return True

def _mark_sent(now: float) -> None:
    global _last_explain_ts, _sent_in_window
    _last_explain_ts = now
    _sent_in_window += 1

def _fmt_pct(x: float) -> str:
    return f"{x:.2f}%"

def _fmt_num(x: float) -> str:
    # קצר, נקי
    if abs(x) >= 1000:
        return f"{x:.2f}"
    if abs(x) >= 1:
        return f"{x:.3f}"
    return f"{x:.6f}"

def _line_for_trade(t: Dict[str, Any]) -> str:
    """
    t keys (as provided by auto_executor plan on success):
    symbol, side, entry, sl, tp, leverage, score, adx, atr, ema21, ema50, macd_hist, rsi
    """
    sym   = str(t.get("symbol","?")).upper()
    side  = str(t.get("side","?")).upper()
    ent   = float(t.get("entry", 0.0))
    sl    = float(t.get("sl", 0.0))
    tp    = float(t.get("tp", 0.0))
    lev   = int(t.get("leverage", 0))
    q     = float(t.get("score", 0.0))
    adx   = float(t.get("adx", 0.0))
    atr   = float(t.get("atr", 0.0))
    e21   = t.get("ema21", None)
    e50   = t.get("ema50", None)
    mh    = t.get("macd_hist", None)
    rsi   = t.get("rsi", None)

    # distances
    try:
        if side == "LONG":
            sl_dist = (ent - sl) / ent * 100.0 if ent > 0 else 0.0
            tp_dist = (tp - ent) / ent * 100.0 if ent > 0 else 0.0
        else:
            sl_dist = (sl - ent) / ent * 100.0 if ent > 0 else 0.0
            tp_dist = (ent - tp) / ent * 100.0 if ent > 0 else 0.0
    except Exception:
        sl_dist, tp_dist = 0.0, 0.0

    ema_rel = ""
    if e21 is not None and e50 is not None:
        if float(e21) > float(e50):
            ema_rel = "EMA21>EMA50"
        elif float(e21) < float(e50):
            ema_rel = "EMA21<EMA50"
        else:
            ema_rel = "EMA21≈EMA50"

    parts = [
        f"• <b>{sym}</b> {side} x{lev} @ {_fmt_num(ent)}",
        f"   SL {_fmt_num(sl)} ({_fmt_pct(sl_dist)}), TP {_fmt_num(tp)} ({_fmt_pct(tp_dist)})",
        f"   ADX {adx:.1f}, ATR {_fmt_num(atr)}; Q={q:.1f}",
    ]
    extra = []
    if ema_rel: extra.append(ema_rel)
    if mh is not None: extra.append(f"MACD {float(mh):+.3f}")
    if rsi is not None: extra.append(f"RSI {float(rsi):.1f}")
    if extra:
        parts.append("   " + ", ".join(extra))
    return "\n".join(parts)

def _format_batch(trades: List[Dict[str, Any]]) -> str:
    ts = time.strftime("%H:%M:%S")
    head = f"📈 <b>Explain Trade</b> ({len(trades)} executed) — {ts}"
    body = "\n".join(_line_for_trade(t) for t in trades)
    out = f"{head}\n{body}"
    # TG hard limit ~4096 chars; נחתוך בנדיבות.
    if len(out) > 3500:
        out = out[:3450] + "\n… (truncated)"
    return out

# ========= Public API =========
async def notify_no_trades():
    # שומר קיים – לא שולחים פה כלום כברירת מחדל
    return None

async def notify_scan_error(reason: str):
    if not _tg_enabled():
        return
    try:
        await _tg_send(f"⚠️ Scan error: <code>{reason}</code>")
    except Exception:
        pass

async def notify_trade_explain_batch(trades: List[Dict[str, Any]]):
    """
    שליחת הודעת Explain אחת לבאצ' של טריידים יוצאים (באותו tick).
    מכבד Cooldown ו-cap לדקה כדי לא להציף.
    """
    if not OPS_EXPLAIN_TRADE_TELEGRAM:
        return
    if not _tg_enabled():
        return
    if not trades:
        return
    now = time.time()
    if not _should_send_explain(now):
        logger.info({"event":"explain_trade_skip", "reason":"throttled"})
        return
    try:
        txt = _format_batch(trades if OPS_EXPLAIN_BATCH else trades[:1])
        await _tg_send(txt)
        _mark_sent(now)
    except Exception as e:
        logger.warning("notify_trade_explain_batch failed: %s", e)









