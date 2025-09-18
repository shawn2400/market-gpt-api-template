# utils/telegram_notifier.py
from __future__ import annotations

import os, asyncio, logging, json, time, math
from typing import Any, Dict, Optional, List, Tuple
from datetime import datetime

from .telegram_notifier_core import (
    BOT_TOKEN, CHAT_ID, API_BASE, PUBLIC_HOST,
    set_explain_enabled, get_explain_enabled,
    EXPLAIN_MIN_SCORE, EXPLAIN_COOLDOWN_SEC, EXPLAIN_MAX_PER_MIN,
    _tg_send, _tg_send_with_markup, _bundle_add,
    _store_change_event, _load_changes_since,
    _fmt_il, _fmt_usd, _fmt_num, _fmt_pct, _fmt_pct_prob, _fmt_eta, _em,
    _fmt_side, _fmt_order_type, _tp_legs_to_lines, _try_get_live_price,
    _ensure_ticket_urls, _build_trade_urls, should_auto_approve_trade,
)

# אמידות / הקשר שוק
try:
    from utils.estimation import (
        estimate_trade_meta,                # probs/eta/expected_pnl, per-TP USD etc.
        get_market_context_summary,        # מצב BTC (מגמה/RSI/ADX קצר)
    )
except Exception:
    async def estimate_trade_meta(plan: Dict[str, Any]) -> Dict[str, Any]: return {}
    def get_market_context_summary() -> str: return "BTC market: —"

logger = logging.getLogger("algogpt.tg")

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
    try: pnl_fmt = f"{float(pnl):.2f}"
    except Exception: pnl_fmt = str(pnl)
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
    if not get_explain_enabled(): return
    if float(plan.get("score", 0.0)) < EXPLAIN_MIN_SCORE: return

    sym   = str(plan.get("symbol","")).upper()
    side  = str(plan.get("side","")).upper()
    lev   = int(plan.get("leverage", 0) or 0)
    entry = float(plan.get("entry", plan.get("entry_price", plan.get("price", 0.0))) or 0.0)
    sl    = float(plan.get("sl", plan.get("sl_price", 0.0)) or 0.0)
    tp    = float(plan.get("tp", 0.0) or 0.0)
    adx   = float(plan.get("adx", plan.get("dyn", {}).get("adx", 0.0)) or 0.0)
    atr   = float(plan.get("atr", plan.get("dyn", {}).get("atr_pct", 0.0)) or 0.0)
    score = float(plan.get("score", 0.0) or 0.0)
    ema21 = plan.get("ema_21"); ema50 = plan.get("ema_50"); macdh = plan.get("macd_hist"); rsi = plan.get("rsi")

    trend_ok = "✓" if (ema21 and ema50 and ((float(ema21) > float(ema50) and side in ("LONG","BUY")) or (float(ema21) < float(ema50) and side in ("SHORT","SELL")))) else "✗"
    macd_ok  = "✓" if (macdh is not None and ((side in ("LONG","BUY") and float(macdh)>0) or (side in ("SHORT","SELL") and float(macdh)<0))) else "✗"

    lines = [
        "⚙️ <b>Explain Trade</b>",
        f"<b>{sym}</b> · <b>{side}</b> · lev=<b>{lev}</b>",
        f"🧭 {get_market_context_summary()}",
    ]
    if ema21 and ema50: lines.append(f"EMA21{'>' if float(ema21)>float(ema50) else '<'}EMA50 {trend_ok}")
    if macdh is not None: lines.append(f"MACD hist {float(macdh):+.4f} {macd_ok}")
    if adx or atr:
        try: lines.append(f"ADX {adx:.0f} | ATR% {float(atr):.2f}" if float(atr) < 10 else f"ADX {adx:.0f} | ATR {float(atr):.4f}")
        except Exception: lines.append(f"ADX {adx:.0f}")
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
    elif isinstance(reason, dict): text = reason.get("why") or reason.get("explain") or reason.get("summary") or ""
    text = text.strip()
    if len(text) > limit: text = text[:limit-1] + "…"
    return text or "—"

def _leg_expected_usd(budget_usd: float, entry: float, tp_px: float, side: str, lev: float, split: float | None) -> float:
    if not all([budget_usd, entry, tp_px, lev]):
        return 0.0
    pct = (tp_px - entry) / entry
    if str(side).upper() in ("SELL","SHORT"):
        pct = -pct
    # split יכול להיות ב־[0..1] או כמות — נתמך באופן גמיש
    split_ratio = 1.0
    try:
        if split is not None:
            s = float(split)
            split_ratio = s if s <= 1.0 else s  # אם הביא כמות, זה קירוב; נשאיר כמו שהוא
    except Exception:
        pass
    return budget_usd * pct * float(lev) * float(split_ratio)

async def send_trade_approval(idem: str, plan: Dict[str, Any], chat_id: Optional[int] = None) -> None:
    symbol  = str(plan.get("symbol","")).upper()
    side    = _fmt_side(str(plan.get("side","")))
    lev     = float(plan.get("leverage") or plan.get("lev") or 0) or 0
    otype   = _fmt_order_type(str(plan.get("order_type") or plan.get("entry_type") or "MARKET"))
    entry   = plan.get("entry_price") or plan.get("limit_price") or plan.get("price")
    now_px  = plan.get("now_price") or _try_get_live_price(symbol)
    sl_obj  = plan.get("sl") or {}
    sl_px   = sl_obj.get("stopPrice") or sl_obj.get("price")
    tp_legs = plan.get("tp") or plan.get("tp_orders") or []
    budget  = float(plan.get("budget_usd") or plan.get("budget") or plan.get("budget_used") or 0.0)
    reason  = plan.get("why") or plan.get("explain") or plan.get("reasons")
    why_txt = _trim_reason(reason)
    kind    = (plan.get("trade_kind") or plan.get("mode") or plan.get("market") or "Futures").capitalize()
    ttl_sec = int(plan.get("ttl_sec") or os.getenv("TRADE_APPROVAL_TTL_SEC", "600"))

    # חיזוי/ETA/הסתברויות
    meta = await estimate_trade_meta(plan)
    probs = meta.get("probs", {})
    eta   = meta.get("eta", {})
    eta_entry = eta.get("entry_sec") or eta.get("entry")

    # רווח משוער לכל TP ב$
    tp_lines = []
    for i, leg in enumerate(tp_legs, start=1):
        px = leg.get("stopPrice") or leg.get("price")
        split = leg.get("qty") or leg.get("size") or leg.get("split")
        est_usd = _leg_expected_usd(budget, float(entry or 0), float(px or 0), str(plan.get("side","")), lev, split)
        line = f"🎯 TP{i}: <code>{_fmt_num(px, 4)}</code> · split <code>{split}</code> · " \
               f"ETA {_fmt_eta(eta.get(f'tp{i}') or eta.get(f'tp{i}_sec'))} · p={_fmt_pct_prob(probs.get(f'tp{i}'))} · " \
               f"≈ {_fmt_usd(est_usd)}"
        tp_lines.append(line)

    overall_p = probs.get("overall") or probs.get("success") or probs.get("p_overall")

    # הקשר שוק (BTC anchor)
    market_line = f"🧭 {get_market_context_summary()}"

    # בניית הודעה
    lines: list[str] = []
    lines.append(f"🟡 <b>Trade Pending Approval</b> · <b>{kind}</b>")
    lines.append(market_line)
    lines.append(f"🪙 <b>{symbol}</b> · {side} · lev <b>{int(lev) if lev.is_integer() else lev}</b> · {otype}")
    lines.append(f"💫 מחיר עכשיו: <code>{_fmt_num(now_px, 4)}</code>")
    lines.append(f"🟦 <b>כניסה</b>: <code>{_fmt_num(entry, 4)}</code> · ⏳ ETA כניסה {_fmt_eta(eta_entry)}")
    lines.append(f"🛡 <b>SL</b>: <code>{_fmt_num(sl_px, 4)}</code>")
    if tp_lines: lines += tp_lines
    lines.append(f"📈 <b>הסתברות כוללת</b>: <b>{_fmt_pct_prob(overall_p)}</b> · P(T1): {_fmt_pct_prob(probs.get('tp1'))} · P(T2): {_fmt_pct_prob(probs.get('tp2'))} · P(T3): {_fmt_pct_prob(probs.get('tp3'))}")
    lines.append(f"💸 <b>השקעה</b>: {_fmt_usd(budget)}")
    if meta.get("expected_pnl_usd") is not None:
        lines.append(f"🎯 <b>יעד רווח (משוער)</b>: {_fmt_usd(meta.get('expected_pnl_usd'))}")
    order_mode = (plan.get("order_type") or plan.get("entry_type") or "MARKET").upper()
    lines.append(f"🧾 <b>סוג הזמנה</b>: {order_mode} · ⏱ TTL לאישור: {ttl_sec}s")
    if 'leverage' in plan:
        lines.append(f"🧮 <b>מינוף</b>: x{int(lev) if lev.is_integer() else lev}")
    if 'allocation_pct' in plan:
        try:
            lines.append(f"📊 <b>Allocation</b>: {float(plan['allocation_pct']):.0f}%")
        except Exception:
            pass
    lines.append(f"🧠 <b>למה נבחר</b>: {why_txt}")
    lines.append("— — —")
    lines.append(f"🕒 {_fmt_il(time.time())}")

    urls = _build_trade_urls(idem, plan)
    kb = {"inline_keyboard":[
        [{"text":"✅ אישור / Approve", "url": urls["approve"]},
         {"text":"❌ דחייה / Reject",  "url": urls["reject"]}],
        ([{"text":"🧾 Ticket", "url": urls["ticket"]}] if urls["ticket"] else [])
    ]}
    await _tg_send_with_markup("\n".join(lines), kb, chat_id=chat_id)

async def send_trade_opened(info: Dict[str, Any]) -> None:
    plan = info.get("plan") or {}
    s = plan.get("symbol",""); side = _fmt_side(plan.get("side",""))
    qty = plan.get("qty",""); price = plan.get("entry_price", plan.get("price",""))
    otype = _fmt_order_type(plan.get("order_type","")); lev = plan.get("leverage","—")
    kind = (plan.get("trade_kind") or plan.get("mode") or plan.get("market") or "Futures").capitalize()
    await _tg_send(f"🟢 <b>Opened</b> · <b>{kind}</b>\n{s} {side} · qty <code>{qty}</code> · ~<code>{_fmt_num(price,4)}</code> · {otype} · lev <b>{lev}</b>")

async def send_trade_update(info: Dict[str, Any]) -> None:
    plan = info.get("plan") or {}
    s = plan.get("symbol",""); side = _fmt_side(plan.get("side",""))
    tp = _tp_legs_to_lines(plan.get("tp")); sl = (plan.get("sl") or {}).get("stopPrice")
    parts = [f"📈 <b>Update</b> {s} {side}", *tp, f"🛡 SL: <code>{_fmt_num(sl,4)}</code>"]
    await _tg_send("\n".join(parts))

async def send_trade_closed(info: Dict[str, Any]) -> None:
    plan = info.get("plan") or {}
    s = (plan.get("symbol") or info.get("symbol") or "").upper()
    side = _fmt_side(plan.get("side",""))
    kind = (plan.get("trade_kind") or plan.get("mode") or plan.get("market") or "Futures").capitalize()

    pnl_usd = info.get("pnl_usd", info.get("pnl"))
    pnl_pct = info.get("pnl_pct")
    dur     = info.get("duration_sec")
    hit     = info.get("hit") or []
    went    = info.get("went_well") or []
    bad     = info.get("to_improve") or []
    scores  = info.get("scorecards") or {}
    overal  = info.get("overall_score")

    entry = plan.get("entry_price") or plan.get("price")
    exit  = info.get("exit_price") or info.get("avg_exit")

    lines = [f"🔴 <b>Closed</b> · <b>{kind}</b> · {s} {side}"]
    lines.append(f"💰 PnL: <b>{_fmt_usd(pnl_usd)}</b> ({_fmt_pct_prob(pnl_pct) if pnl_pct is not None else '—'})")
    lines.append(f"🎯 Hit: {', '.join(hit) if hit else '—'}")
    lines.append(f"⏱ Duration: {_fmt_eta(dur)}")
    lines.append(f"↔️ Prices: entry <code>{_fmt_num(entry,4)}</code> → exit <code>{_fmt_num(exit,4)}</code>")
    if went:
        lines.append("✅ Went well:")
        for x in went[:5]: lines.append(f"  • {x}")
    if bad:
        lines.append("⚠️ To improve:")
        for x in bad[:5]: lines.append(f"  • {x}")
    if scores:
        lines.append("🧪 Scores:")
        for k,v in scores.items():
            try: lines.append(f"  • {k}: {int(float(v))}/10")
            except Exception: lines.append(f"  • {k}: —")
    if overal is not None:
        try: lines.append(f"🏁 Overall: <b>{int(float(overal))}/10</b>")
        except Exception: pass
    await _tg_send("\n".join(lines))

# ===================== Change Tickets (כמו שהיה) =====================
from .telegram_notifier_core import (
    format_change_approval_he, send_change_approval_he, route_change_ticket,
    send_ops_digest_now, send_eod_report_now, ensure_ops_schedulers_started,
)

__all__ = [
    "set_explain_enabled", "get_explain_enabled",
    "notify_no_trades", "notify_scan_error", "notify_explain_trade",
    "notify_sl_tp_update", "notify_info", "notify_error",
    "notify_heartbeat", "notify_daily_summary", "notify_ops_alert",
    "register_webhook",
    "send_trade_approval", "send_trade_opened", "send_trade_update", "send_trade_closed",
    "format_change_approval_he", "send_change_approval_he", "route_change_ticket",
    "send_ops_digest_now", "send_eod_report_now", "ensure_ops_schedulers_started",
    "should_auto_approve_trade",
]


