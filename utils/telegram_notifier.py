# utils/telegram_notifier.py
from __future__ import annotations

import os, asyncio, logging, json, time
from typing import Any, Dict, Optional, List

from .telegram_notifier_core import (
    BOT_TOKEN, CHAT_ID, API_BASE, PUBLIC_HOST,
    set_explain_enabled, get_explain_enabled,
    EXPLAIN_MIN_SCORE, EXPLAIN_COOLDOWN_SEC, EXPLAIN_MAX_PER_MIN,
    _tg_send, _tg_send_with_markup, _bundle_add,
    _store_change_event, _load_changes_since,
    _fmt_il, _fmt_usd, _fmt_num, _fmt_pct, _fmt_pct_prob, _fmt_eta, _em,
    _fmt_side, _fmt_order_type, _tp_legs_to_lines, _try_get_live_price,
    _ensure_ticket_urls, _build_trade_urls, should_auto_approve_trade,
    get_btc_anchor_summary,
)

logger = logging.getLogger("algogpt.tg")

# ===================== Estimation helpers (optional) =====================
try:
    from utils.estimation import (
        make_estimations,  # returns {"probs": {...}, "eta": {...}, "tp_profit_usd": {...}, "expected_pnl_usd": float | None}
        market_summary,    # short BTC market line (optional)
    )
except Exception:
    def make_estimations(plan: Dict[str, Any]) -> Dict[str, Any]:
        return {"probs": plan.get("probs") or {}, "eta": plan.get("eta") or {}, "tp_profit_usd": {}, "expected_pnl_usd": plan.get("expected_pnl_usd")}
    def market_summary() -> str:
        return get_btc_anchor_summary()

# ===================== Basic Ops Notifications =====================
async def notify_no_trades() -> None:
    if os.getenv("SCAN_NO_TRADES_NOTIFY","0").lower() in ("1","true","yes","on"):
        await _tg_send("🔍 לא נמצאו טריידים תואמים בחלון הסריקה.")

async def notify_scan_error(reason: str) -> None:
    txt = f"⚠️ <b>Scan error</b>\n<code>{reason}</code>"
    await _bundle_add(txt.replace("\n", " | "))

async def notify_ops_alert(msg: str) -> None:
    await _bundle_add(f"🛠 {msg}")

async def notify_sl_tp_update(symbol: str, side: str, kind: str, value: Any) -> None:
    try:
        val = f"{float(value):.4f}"
    except Exception:
        val = str(value)
    await _tg_send(f"🔧 <b>{symbol}</b> {side} · {kind.upper()} → <code>{val}</code>")

async def notify_info(text: str) -> None:  await _tg_send(f"ℹ️ {text}")
async def notify_error(text: str) -> None: await _tg_send(f"🚨 {text}")
async def notify_heartbeat() -> None:      await _tg_send("🫀 Heartbeat OK")

async def notify_daily_summary(summary: Dict[str, Any]) -> None:
    pnl = summary.get("pnl", 0.0); t = summary.get("time", ""); n = len(summary.get("trades") or [])
    try:
        pnl_fmt = f"{float(pnl):.2f}"
    except Exception:
        pnl_fmt = str(pnl)
    await _tg_send(f"📘 Daily Summary {t}\nPnL: <b>{pnl_fmt}</b> USDT · trades={n}")

# ===================== Webhook Registration =====================
async def register_webhook() -> bool:
    public_host = PUBLIC_HOST
    secret_token = os.getenv("TELEGRAM_WEBHOOK_SECRET", "").strip()
    if not BOT_TOKEN or not public_host or not secret_token:
        return False
    try:
        import httpx
        async with httpx.AsyncClient(timeout=10.0) as cli:
            r = await cli.post(f"{API_BASE}/setWebhook", data={
                "url": f"{public_host}/telegram/webhook",
                "secret_token": secret_token,
                "drop_pending_updates": "true",
                "max_connections": "40",
            })
            return r.status_code == 200 and r.json().get("ok", False)
    except Exception as e:
        logger.warning({"event": "register_webhook_failed", "error": str(e)})
        return False

# ===================== Explain Trade (throttled) =====================
_last_explain_ts: float = 0.0
_sent_in_win: int = 0
_win_start: float = 0.0

async def notify_explain_trade(plan: Dict[str, Any]) -> None:
    if not get_explain_enabled():
        return
    if float(plan.get("score", 0.0)) < EXPLAIN_MIN_SCORE:
        return

    sym   = str(plan.get("symbol", "")).upper()
    side  = str(plan.get("side", "")).upper()
    lev   = int(plan.get("leverage", 0) or 0)
    entry = float(plan.get("entry", plan.get("entry_price", plan.get("price", 0.0))) or 0.0)
    sl    = float(plan.get("sl", plan.get("sl_price", 0.0)) or 0.0)
    tp    = float(plan.get("tp", 0.0) or 0.0)
    adx   = float(plan.get("adx", plan.get("dyn", {}).get("adx", 0.0)) or 0.0)
    atr   = float(plan.get("atr", plan.get("dyn", {}).get("atr_pct", 0.0)) or 0.0)
    score = float(plan.get("score", 0.0) or 0.0)
    ema21 = plan.get("ema_21"); ema50 = plan.get("ema_50"); macdh = plan.get("macd_hist"); rsi = plan.get("rsi")

    trend_ok = "✓" if (ema21 and ema50 and ((float(ema21) > float(ema50) and side in ("LONG","BUY")) or (float(ema21) < float(ema50) and side in ("SHORT","SELL")))) else "✗"
    macd_ok  = "✓" if (macdh is not None and ((side in ("LONG","BUY") and float(macdh) > 0) or (side in ("SHORT","SELL") and float(macdh) < 0))) else "✗"

    lines = [
        "⚙️ <b>Explain Trade</b>",
        f"<b>{sym}</b> · <b>{side}</b> · lev=<b>{lev}</b>",
        market_summary() if callable(market_summary) else get_btc_anchor_summary(),
    ]
    if ema21 and ema50: lines.append(f"EMA21{'>' if float(ema21) > float(ema50) else '<'}EMA50 {trend_ok}")
    if macdh is not None: lines.append(f"MACD hist {float(macdh):+.4f} {macd_ok}")
    if adx or atr:
        try:
            lines.append(f"ADX {adx:.0f} | ATR% {float(atr):.2f}" if float(atr) < 10 else f"ADX {adx:.0f} | ATR {float(atr):.4f}")
        except Exception:
            lines.append(f"ADX {adx:.0f}")
    if rsi is not None:
        try: lines.append(f"RSI {float(rsi):.1f}")
        except Exception: pass
    lines.append(f"Quality Score: <b>{score:.2f}/10</b>")
    if entry and (sl or tp):
        try: lines.append(f"Entry {entry:.4f} | SL {sl:.4f} | TP {tp:.4f}")
        except Exception: lines.append(f"Entry {entry} | SL {sl} | TP {tp}")
    await _tg_send("\n".join(lines))

# ===================== Trade Approval (rich) =====================
def _trim_reason(reason: Any, limit: int = 240) -> str:
    text = ""
    if isinstance(reason, str): text = reason
    elif isinstance(reason, list): text = "; ".join([str(x) for x in reason if x])
    elif isinstance(reason, dict): text =



