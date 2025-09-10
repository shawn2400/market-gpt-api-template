# utils/telegram_notifier.py
from __future__ import annotations
import os, time, asyncio, logging
from typing import Any, Dict, Optional

logger = logging.getLogger("algogpt.tg")

BOT_TOKEN      = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
CHAT_ID        = int(os.getenv("TELEGRAM_CHAT_ID", "0") or 0)
API_BASE       = f"https://api.telegram.org/bot{BOT_TOKEN}" if BOT_TOKEN else ""

# Explain flags (ניתנים לטוגל בזמן אמת)
_EXPLAIN_ON              = os.getenv("OPS_EXPLAIN_TRADE_TELEGRAM", "1").lower() in ("1","true","yes","on")
EXPLAIN_COOLDOWN_SEC     = int(os.getenv("OPS_EXPLAIN_COOLDOWN_SEC", "45"))
EXPLAIN_MAX_PER_MIN      = int(os.getenv("OPS_EXPLAIN_MAX_PER_MIN", "6"))
EXPLAIN_MIN_SCORE        = float(os.getenv("OPS_EXPLAIN_MIN_SCORE", "0"))

_last_explain_ts: float = 0.0
_win_start: float = 0.0
_sent_in_win: int = 0

def set_explain_enabled(v: bool) -> None:
    global _EXPLAIN_ON
    _EXPLAIN_ON = bool(v)

def get_explain_enabled() -> bool:
    return bool(_EXPLAIN_ON)

async def _tg_send(text: str, chat_id: Optional[int] = None):
    if not BOT_TOKEN or (chat_id is None and CHAT_ID == 0):
        logger.debug({"event":"tg.skip_send","reason":"missing_token_or_chat"})
        return
    cid = chat_id if chat_id is not None else CHAT_ID
    try:
        import httpx
        async with httpx.AsyncClient(timeout=10.0) as cli:
            await cli.post(f"{API_BASE}/sendMessage", data={
                "chat_id": cid,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True
            })
    except Exception as e:
        logger.warning({"event":"tg.send_failed","error":str(e)})

def _win_tick():
    global _win_start, _sent_in_win
    now = time.time()
    if _win_start == 0.0 or (now - _win_start) >= 60.0:
        _win_start = now
        _sent_in_win = 0

async def notify_no_trades():
    return None

async def notify_scan_error(reason: str):
    await _tg_send(f"⚠️ <b>Scan error</b>\n<code>{reason}</code>")

async def notify_explain_trade(plan: Dict[str, Any]):
    if not _EXPLAIN_ON:
        return
    if float(plan.get("score", 0.0)) < EXPLAIN_MIN_SCORE:
        return

    global _last_explain_ts, _sent_in_win
    _win_tick()

    now = time.time()
    if _last_explain_ts and (now - _last_explain_ts) < EXPLAIN_COOLDOWN_SEC:
        return
    if _sent_in_win >= max(1, EXPLAIN_MAX_PER_MIN):
        return

    sym   = str(plan.get("symbol","")).upper()
    side  = str(plan.get("side","")).upper()
    lev   = int(plan.get("leverage", 0) or 0)
    entry = float(plan.get("entry", 0.0) or 0.0)
    sl    = float(plan.get("sl", 0.0) or 0.0)
    tp    = float(plan.get("tp", 0.0) or 0.0)
    adx   = float(plan.get("adx", 0.0) or 0.0)
    atr   = float(plan.get("atr", 0.0) or 0.0)
    score = float(plan.get("score", 0.0) or 0.0)

    ema21 = plan.get("ema_21", None)
    ema50 = plan.get("ema_50", None)
    macdh = plan.get("macd_hist", None)
    rsi   = plan.get("rsi", None)

    trend_ok = "✓" if (ema21 is not None and ema50 is not None and float(ema21) > float(ema50) and side=="LONG") \
        or (ema21 is not None and ema50 is not None and float(ema21) < float(ema50) and side=="SHORT") else "✗"
    macd_ok = "✓" if (macdh is not None and ((side=="LONG" and float(macdh) > 0) or (side=="SHORT" and float(macdh) < 0))) else "✗"

    lines = []
    lines.append("⚙️ <b>Explain Trade</b>")
    lines.append(f"<b>{sym}</b> · <b>{side}</b> · lev=<b>{lev}</b>")
    if ema21 is not None and ema50 is not None:
        lines.append(f"EMA21{'>' if float(ema21)>float(ema50) else '<'}EMA50 {trend_ok}")
    if macdh is not None:
        lines.append(f"MACD hist {float(macdh):+.4f} {macd_ok}")
    lines.append(f"ADX {adx:.0f} | ATR {atr:.4f}")
    if rsi is not None:
        lines.append(f"RSI {float(rsi):.1f}")
    lines.append(f"Quality Score: <b>{score:.2f}/10</b>")
    if entry and (sl or tp):
        lines.append(f"Entry {entry:.4f} | SL {sl:.4f} | TP {tp:.4f}")

    await _tg_send("\n".join(lines))
    _last_explain_ts = now
    _sent_in_win += 1











