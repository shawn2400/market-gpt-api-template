# utils/telegram_notifier.py
from __future__ import annotations

import os, asyncio, logging, json, time, hmac, hashlib
from typing import Any, Dict, Optional, List

from .telegram_notifier_core import (
    # cfg
    BOT_TOKEN, CHAT_ID, API_BASE, PUBLIC_HOST,
    # explain flags
    set_explain_enabled, get_explain_enabled,
    EXPLAIN_MIN_SCORE,
    # send helpers
    _tg_send, _tg_send_with_markup, _bundle_add,
    # (חדש) מסנני שליחה
    notify_telegram, notify_telegram_with_markup, should_notify,
    # store / digests
    _store_change_event, _load_changes_since,
    # fmt helpers
    _fmt_il, _fmt_usd, _fmt_num, _fmt_pct_prob, _fmt_eta, _em,
    _fmt_side, _fmt_order_type, _tp_legs_to_lines, _try_get_live_price,
    # urls / approvals
    _ensure_ticket_urls, _build_trade_urls, should_auto_approve_trade,
    # market anchor
    get_btc_anchor_summary,
)

logger = logging.getLogger("algogpt.tg")

# ========= Optional estimation helpers (best-effort) =========
try:
    from utils.estimation import make_estimations  # returns {probs, eta, tp_profit_usd, expected_pnl_usd}
except Exception:
    def make_estimations(plan: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "probs": plan.get("prob") or plan.get("probs") or {},
            "eta": plan.get("eta") or {},
            "tp_profit_usd": {},
            "expected_pnl_usd": plan.get("expected_pnl_usd"),
        }

# ====== Alias לשמירה על תאימות ישנה (מודולים שעדיין קוראים _send) ======
async def _send(text: str) -> None:
    # שומר תאימות — שולח ללא פילטר; ממולץ להעדיף notify_telegram מהיום והלאה
    await _tg_send(text)

# ===================== Callback signing/verification =====================
_SIGN_SECRET = (os.getenv("OPS_SIGN_SECRET","") or os.getenv("API_SIGNING_SECRET","")).encode("utf-8")
_CB_TTL_SEC  = int(os.getenv("SIGNED_NONCE_TTL_SEC", os.getenv("ANTI_REPLAY_WINDOW_SEC","120")) or "120")
_SKEW_SEC    = int(os.getenv("SIGNED_TS_MAX_SKEW_SEC","60") or "60")

def _hmac(data: str) -> str:
    if not _SIGN_SECRET:
        return ""
    return hmac.new(_SIGN_SECRET, data.encode("utf-8"), hashlib.sha256).hexdigest()

def make_callback(action: str, trade_id: Optional[str] = None, symbol: Optional[str] = None, pct: Optional[float] = None) -> str:
    """
    יוצר callback_data חתום (אם יש secret). פורמטים נתמכים:
    - CONFIRM:<APPROVE|REJECT>:<trade_id>[:<ts>:<sig>]
    - POS:<ACTION>:<symbol>[:<pct>][:<ts>:<sig>]
    """
    base: List[str] = []
    now = int(time.time())
    if action in ("APPROVE","REJECT"):
        base = ["CONFIRM", action, str(trade_id or "")]
    else:
        base = ["POS", action, str(symbol or "")]
        if pct is not None:
            base.append(f"{float(pct)}")
    data = ":".join(base)
    if not _SIGN_SECRET:
        return data
    raw = f"{data}:{now}"
    sig = _hmac(raw)
    return f"{raw}:{sig}"

def verify_callback_data(data: str) -> Dict[str, Any]:
    """
    מאמת ומפרק callback_data. כאשר מוגדר סוד חתימה — חובה צמד ts+sig.
    מחזיר dict עם action / trade_id / symbol / pct.
    """
    parts = (data or "").split(":")
    if len(parts) < 3:
        raise ValueError("bad_format")

    if parts[0] == "CONFIRM":
        action   = parts[1].upper()
        trade_id = parts[2]
        if action not in ("APPROVE","REJECT"):
            raise ValueError("bad_action")
        if _SIGN_SECRET:
            if len(parts) < 5:
                raise ValueError("unsigned_callback")
            ts  = int(float(parts[-2]))
            sig = parts[-1]
            raw = ":".join(parts[:-1])
            if sig != _hmac(raw):
                raise ValueError("bad_sig")
            now = int(time.time())
            if abs(now - ts) > max(_CB_TTL_SEC, _SKEW_SEC):
                raise ValueError("expired")
        return {"action": action, "trade_id": trade_id}

    if parts[0] == "POS":
        action = parts[1].upper()
        symbol = parts[2]
        pct: Optional[float] = None
        tail = parts[3:]
        ts = None; sig = None
        if tail:
            if len(tail) >= 2:
                try:
                    maybe_ts = int(float(tail[-2]))
                    ts = maybe_ts
                    sig = tail[-1]
                    tail = tail[:-2]
                except Exception:
                    ts = None
                    sig = None
            if tail:
                try:
                    pct = float(tail[0])
                except Exception:
                    pct = None
        if _SIGN_SECRET:
            if ts is None or sig is None:
                raise ValueError("unsigned_callback")
            raw = ":".join(parts[:-1])
            if sig != _hmac(raw):
                raise ValueError("bad_sig")
            now = int(time.time())
            if abs(now - ts) > max(_CB_TTL_SEC, _SKEW_SEC):
                raise ValueError("expired")
        return {"action": action, "symbol": symbol, "pct": pct}

    raise ValueError("unknown_prefix")

# ===================== Inline keyboards (local builders) =====================
def _approval_kb_for_trade(idem: str, ticket_url: Optional[str] = None) -> Dict[str, Any]:
    rows: List[List[Dict[str,Any]]] = [
        [
            {"text": "✅ אישור / Approve", "callback_data": make_callback("APPROVE", trade_id=idem)},
            {"text": "❌ דחייה / Reject",  "callback_data": make_callback("REJECT",  trade_id=idem)},
        ]
    ]
    if ticket_url:
        rows.append([{"text": "🧾 Ticket", "url": ticket_url}])
    return {"inline_keyboard": rows}

# ——— PUBLIC helper so routes/manager.py can import it without error ———
def build_ticket_buttons(trade_id: str, ticket_url: Optional[str] = None) -> Dict[str, Any]:
    """מחזיר ReplyMarkup לאישור/דחייה + לינק טיקט (אם קיים)."""
    return _approval_kb_for_trade(trade_id, ticket_url=ticket_url)

def _ops_action_kb(symbol: str) -> Dict[str,Any]:
    return {"inline_keyboard":[
        [{"text":"⚙️ Manage Again","callback_data": make_callback("MANAGE_AGAIN", symbol=symbol)}],
        [{"text":"🧹 Cancel TPs","callback_data": make_callback("CANCEL_TPS", symbol=symbol)},
         {"text":"➗ Close 50%","callback_data": make_callback("CLOSE_50", symbol=symbol, pct=50.0)}],
    ]}

# ===================== שירות לטלגרם (answer/edit/webhook/results) =====================
class TelegramNotifier:
    @staticmethod
    async def ensure_webhook() -> bool:
        try:
            return await register_webhook()
        except Exception:
            return False

    @staticmethod
    async def answer_callback(cb_id: str, text: str = "", show_alert: bool = False) -> None:
        if not API_BASE or not cb_id:
            return
        import httpx
        async with httpx.AsyncClient(timeout=8.0) as cli:
            await cli.post(f"{API_BASE}/answerCallbackQuery", json={
                "callback_query_id": cb_id,
                "text": text or "",
                "show_alert": bool(show_alert),
            })

    @staticmethod
    async def edit_message_buttons(chat_id: str | int, message_id: int, disable_all: bool = False,
                                   new_kb: Optional[Dict[str,Any]] = None) -> None:
        if not API_BASE:
            return
        kb: Dict[str,Any] = new_kb or {}
        if disable_all and not new_kb:
            kb = {"inline_keyboard": []}
        import httpx
        async with httpx.AsyncClient(timeout=8.0) as cli:
            await cli.post(f"{API_BASE}/editMessageReplyMarkup", json={
                "chat_id": chat_id,
                "message_id": int(message_id),
                "reply_markup": kb
            })

    @staticmethod
    async def send_ops_action_result(symbol: str, action_name: str, chat_id: Optional[int] = None) -> None:
        text = f"✅ {symbol} · {action_name} done"
        kb   = _ops_action_kb(symbol)
        # פעולה אופרטיבית: נסווג kind="ops"
        await notify_telegram_with_markup(text, kb, level="warning", kind="ops", chat_id=chat_id, dedupe_key=f"ops:{symbol}:{action_name}", cooldown_sec=30)

    # ——— new: used by routes/manager.py after ingest ———
    @staticmethod
    async def send_ticket(
        trade_id: str,
        symbol: str,
        side: str,
        timeframe: str = "15m",
        reason: str = "",
        score: float | int = 0,
        extra: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        שולח הודעת אישור עשירה לטיקט חדש (תואם לשימוש ב־routes/manager.py).
        """
        plan: Dict[str, Any] = dict(extra or {})
        plan.setdefault("symbol", symbol)
        plan.setdefault("side", side)
        plan.setdefault("timeframe", timeframe)
        plan.setdefault("why", reason)
        plan.setdefault("score", score)
        plan.setdefault("order_type", plan.get("entry_type", "MARKET"))
        plan.setdefault("leverage", plan.get("lev", plan.get("leverage", 0)))
        if "approve_url" not in plan or "reject_url" not in plan or "ticket_url" not in plan:
            urls = _build_trade_urls(trade_id, plan)
            plan.setdefault("approve_url", urls["approve"])
            plan.setdefault("reject_url",  urls["reject"])
            plan.setdefault("ticket_url",  urls["ticket"])
        await send_trade_approval(trade_id, plan, chat_id=None)

# ===================== Basic Ops Notifications =====================
async def notify_no_trades(reason: str | None = None, low_scores: Optional[List[Dict[str, Any]]] = None) -> None:
    if os.getenv("SCAN_NO_TRADES_NOTIFY", "0").lower() not in ("1", "true", "yes", "on"):
        return
    lines = ["📭 לא נמצאו טריידים תואמים לסף.", "No matching trades at the moment."]
    if reason:
        lines.append(f"ℹ️ {reason}")
    if low_scores:
        try:
            best = sorted(low_scores, key=lambda x: float(x.get("score", 0)), reverse=True)[:3]
            if best:
                lines.append("— — —")
                for b in best:
                    lines.append(f"• {b.get('symbol','?')} · s={float(b.get('score',0)):.1f} · side={b.get('side','—')}")
        except Exception:
            pass
    await notify_telegram("\n".join(lines), level="info", kind="status", dedupe_key="scan:no_trades", cooldown_sec=300)

async def notify_scan_error(reason: str) -> None:
    txt = f"⚠️ <b>Scan error</b>\n<code>{reason}</code>"
    await notify_telegram(txt.replace("\n", " | "), level="warning", kind="ops", dedupe_key="scan:error", cooldown_sec=60)

async def notify_ops_alert(msg: str) -> None:
    await notify_telegram(f"🛠 {msg}", level="warning", kind="ops", dedupe_key=f"ops:{hashlib.sha1(msg.encode()).hexdigest()[:8]}", cooldown_sec=60)

async def notify_sl_tp_update(symbol: str, side: str, kind: str, value: Any) -> None:
    try:
        val = f"{float(value):.4f}"
    except Exception:
        val = str(value)
    await notify_telegram(f"🔧 <b>{symbol}</b> {side} · {kind.upper()} → <code>{val}</code>", level="warning", kind="status", dedupe_key=f"upd:{symbol}:{kind}:{val}", cooldown_sec=60)

async def notify_info(text: str) -> None:
    await notify_telegram(f"ℹ️ {text}", level="info", kind="ops", dedupe_key=f"info:{hashlib.sha1(text.encode()).hexdigest()[:8]}", cooldown_sec=60)

async def notify_error(text: str) -> None:
    await notify_telegram(f"🚨 {text}", level="error", kind="ops", dedupe_key=f"err:{hashlib.sha1(text.encode()).hexdigest()[:8]}", cooldown_sec=60)

async def notify_heartbeat() -> None:
    await notify_telegram("🫀 Heartbeat OK", level="info", kind="status", dedupe_key="hb", cooldown_sec=600)

async def notify_daily_summary(summary: Dict[str, Any]) -> None:
    pnl = summary.get("pnl", 0.0)
    t = summary.get("time", "")
    n = len(summary.get("trades") or [])
    try:
        pnl_fmt = f"{float(pnl):.2f}"
    except Exception:
        pnl_fmt = str(pnl)
    await notify_telegram(f"📘 Daily Summary {t}\nPnL: <b>{pnl_fmt}</b> USDT · trades={n}", level="info", kind="ops", dedupe_key=f"eod:{t}", cooldown_sec=600)

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

# ===================== Explain Trade =====================
def _trim_reason(reason: Any, limit: int = 240) -> str:
    text = ""
    if isinstance(reason, str):
        text = reason
    elif isinstance(reason, list):
        text = "; ".join([str(x) for x in reason if x])
    elif isinstance(reason, dict):
        text = reason.get("why") or reason.get("explain") or reason.get("summary") or ""
    text = text.strip()
    if len(text) > limit:
        text = text[: limit - 1] + "…"
    return text or "—"

async def notify_explain_trade(plan: Dict[str, Any]) -> None:
    if not get_explain_enabled():
        return
    if float(plan.get("score", 0.0)) < EXPLAIN_MIN_SCORE:
        return

    sym   = str(plan.get("symbol", "")).upper()
    side0 = str(plan.get("side", "")).upper()
    lev   = int(plan.get("leverage", 0) or 0)
    entry = float(plan.get("entry", plan.get("entry_price", plan.get("price", 0.0))) or 0.0)
    sl    = float(plan.get("sl", plan.get("sl_price", 0.0)) or 0.0)
    tp    = float(plan.get("tp", 0.0) or 0.0)
    adx   = float(plan.get("adx", plan.get("dyn", {}).get("adx", 0.0)) or 0.0)
    atr   = float(plan.get("atr", plan.get("dyn", {}).get("atr_pct", 0.0)) or 0.0)
    score = float(plan.get("score", 0.0) or 0.0)
    ema21 = plan.get("ema_21"); ema50 = plan.get("ema_50")
    macdh = plan.get("macd_hist"); rsi = plan.get("rsi")

    trend_ok = "✓" if (ema21 and ema50 and ((float(ema21) > float(ema50) and side0 in ("LONG", "BUY")) or (float(ema21) < float(ema50) and side0 in ("SHORT", "SELL")))) else "✗"
    macd_ok  = "✓" if (macdh is not None and ((side0 in ("LONG", "BUY") and float(macdh) > 0) or (side0 in ("SHORT", "SELL") and float(macdh) < 0))) else "✗"

    lines = [
        "⚙️ <b>Explain Trade</b>",
        f"<b>{sym}</b> · <b>{side0}</b> · lev=<b>{lev}</b>",
        get_btc_anchor_summary(),
    ]
    if ema21 and ema50:
        lines.append(f"EMA21{'>' if float(ema21) > float(ema50) else '<'}EMA50 {trend_ok}")
    if macdh is not None:
        try:
            lines.append(f"MACD hist {float(macdh):+.4f} {macd_ok}")
        except Exception:
            lines.append(f"MACD hist {macd_ok}")
    if adx or atr:
        try:
            lines.append(f"ADX {adx:.0f} | ATR% {float(atr):.2f}" if float(atr) < 10 else f"ADX {adx:.0f} | ATR {float(atr):.4f}")
        except Exception:
            lines.append(f"ADX {adx:.0f}")
    if rsi is not None:
        try:
            lines.append(f"RSI {float(rsi):.1f}")
        except Exception:
            pass
    lines.append(f"Quality Score: <b>{score:.2f}/10</b>")
    if entry and (sl or tp):
        try:
            lines.append(f"Entry {entry:.4f} | SL {sl:.4f} | TP {tp:.4f}")
        except Exception:
            lines.append(f"Entry {entry} | SL {sl} | TP {tp}")
    await notify_telegram("\n".join(lines), level="info", kind="trade", dedupe_key=f"explain:{sym}:{side0}", cooldown_sec=60)

# ===================== Trade Approval (rich) =====================
def _entry_score_badge(plan: Dict[str, Any]) -> Optional[str]:
    # אם הלקוח סיפק badges ידניים — נציג אותם (מרובים) עם רווחים
    badges = plan.get("badges")
    if isinstance(badges, list) and badges:
        return " ".join(str(b) for b in badges)

    # Badge אוטומטי לפי blocked_by_entry_score / entry_score(+min)
    blocked = bool(plan.get("blocked_by_entry_score", False))
    score   = plan.get("entry_score")
    min_s   = plan.get("entry_score_min")
    try:
        s = float(score) if score is not None else float("nan")
    except Exception:
        s = float("nan")
    try:
        m = float(min_s) if min_s is not None else float("nan")
    except Exception:
        m = float("nan")

    if blocked:
        if s == s and m == m:
            return f"⚠️ BLOCKED_BY_ENTRY_SCORE (s={s:.2f} < min={m:.2f})"
        return "⚠️ BLOCKED_BY_ENTRY_SCORE"
    # passed/neutral
    if m == m and m > 0 and s == s:
        if s >= m:
            return f"✅ ENTRY SCORE OK (s={s:.2f} ≥ min={m:.2f})"
    return "✅ ENTRY READY"

async def send_trade_approval(idem: str, plan: Dict[str, Any], chat_id: Optional[int] = None) -> None:
    est     = make_estimations(plan)
    probs   = est.get("probs") or {}
    eta     = est.get("eta") or {}
    tp_pnl  = est.get("tp_profit_usd") or {}
    exp_pnl = est.get("expected_pnl_usd")

    symbol  = str(plan.get("symbol", "")).upper()
    side    = _fmt_side(str(plan.get("side", "")))
    lev     = plan.get("leverage") or plan.get("lev") or "—"
    otype   = _fmt_order_type(str(plan.get("order_type") or plan.get("entry_type") or "MARKET"))
    entry   = plan.get("entry_price") or plan.get("limit_price") or plan.get("price")
    now_px  = plan.get("now_price") or _try_get_live_price(symbol)
    sl_obj  = plan.get("sl") or {}
    sl_px   = sl_obj.get("stopPrice") or sl_obj.get("price")
    tp_legs = plan.get("tp") or plan.get("tp_orders") or []
    budget  = plan.get("budget_usd") or plan.get("budget") or plan.get("budget_used")
    ttl_sec = int(plan.get("ttl_sec") or os.getenv("TRADE_APPROVAL_TTL_SEC", "600"))
    eta_entry = (eta or {}).get("entry_sec") or (eta or {}).get("entry")

    reason  = plan.get("why") or plan.get("explain") or plan.get("reasons")
    def _trim_reason_local(reason: Any, limit: int = 240) -> str:
        text = ""
        if isinstance(reason, str):
            text = reason
        elif isinstance(reason, list):
            text = "; ".join([str(x) for x in reason if x])
        elif isinstance(reason, dict):
            text = reason.get("why") or reason.get("explain") or reason.get("summary") or ""
        text = text.strip()
        if len(text) > limit:
            text = text[: limit - 1] + "…"
        return text or "—"
    why_txt = _trim_reason_local(reason)
    kind    = (plan.get("trade_kind") or plan.get("mode") or plan.get("market") or "Futures").capitalize()

    tp_lines = _tp_legs_to_lines(tp_legs, eta=eta, probs=probs)
    if tp_lines and tp_pnl:
        new_lines = []
        for i, line in enumerate(tp_lines, start=1):
            gas = tp_pnl.get(f"tp{i}")
            new_lines.append(line + (f" · ⛽ {_fmt_usd(gas)}" if gas is not None else ""))
        tp_lines = new_lines

    overall_p = probs.get("overall") or probs.get("success") or probs.get("p_overall")
    market_line = get_btc_anchor_summary()

    # ===== headline =====
    title = f"🟡 <b>Trade Pending Approval</b> · <b>{kind}</b>"
    badge = _entry_score_badge(plan)

    lines: List[str] = []
    lines.append(title)
    if badge:
        lines.append(badge)
    lines.append(market_line)
    lines.append(f"🪙 <b>{symbol}</b> · {side} · lev <b>{lev}</b> · {otype}")
    lines.append(f"💫 מחיר עכשיו: <code>{_fmt_num(now_px, 4)}</code>")
    lines.append(f"🟦 <b>כניסה</b>: <code>{_fmt_num(entry, 4)}</code> · ⏳ ETA כניסה {_fmt_eta(eta_entry)}")
    lines.append(f"🛡 <b>SL</b>: <code>{_fmt_num(sl_px, 4)}</code>")
    if tp_lines:
        lines += tp_lines
    lines.append(
        f"📈 <b>הסתברות כוללת</b>: <b>{_fmt_pct_prob(overall_p)}</b> · "
        f"P(T1): {_fmt_pct_prob((probs or {}).get('tp1'))} · "
        f"P(T2): {_fmt_pct_prob((probs or {}).get('tp2'))} · "
        f"P(T3): {_fmt_pct_prob((probs or {}).get('tp3'))}"
    )
    lines.append(f"💸 <b>השקעה</b>: {_fmt_usd(budget)}")
    if exp_pnl is not None:
        lines.append(f"🎯 <b>יעד רווח (משוער)</b>: {_fmt_usd(exp_pnl)}")
    order_mode = (plan.get("order_type") or plan.get("entry_type") or "MARKET").upper()
    lines.append(f"🧾 <b>סוג הזמנה</b>: {order_mode} · ⏱ TTL לאישור: {ttl_sec}s")
    if 'leverage' in plan:
        try:
            levf = float(lev)
            lines.append(f"🧮 <b>מינוף</b>: x{int(levf) if levf.is_integer() else levf}")
        except Exception:
            pass
    if 'allocation_pct' in plan:
        try:
            lines.append(f"📊 <b>Allocation</b>: {float(plan['allocation_pct']):.0f}%")
        except Exception:
            pass
    lines.append(f"🧠 <b>למה נבחר</b>: {why_txt}")
    lines.append("— — —")
    lines.append(f"🕒 {_fmt_il(time.time())}")

    urls = _build_trade_urls(idem, plan)
    kb = _approval_kb_for_trade(idem, ticket_url=urls.get("ticket"))
    # אישור טרייד — קריטי, וייסווג כ-kind="approve" כדי לעבור מסנן trade-only
    await notify_telegram_with_markup("\n".join(lines), kb, level="critical", kind="approve", chat_id=chat_id, dedupe_key=f"approve:{idem}", cooldown_sec=5, force=False)

# ===================== Trade lifecycle short notifiers =====================
async def send_trade_opened(info: Dict[str, Any]) -> None:
    plan = info.get("plan") or {}
    s = plan.get("symbol", "")
    side = _fmt_side(plan.get("side", ""))
    qty = plan.get("qty", "")
    price = plan.get("entry_price", plan.get("price", ""))
    otype = _fmt_order_type(plan.get("order_type", ""))
    lev = plan.get("leverage", "—")
    kind = (plan.get("trade_kind") or plan.get("mode") or plan.get("market") or "Futures").capitalize()
    await notify_telegram(
        f"🟢 <b>Opened</b> · <b>{kind}</b>\n"
        f"{s} {side} · qty <code>{qty}</code> · ~<code>{_fmt_num(price,4)}</code> · {otype} · lev <b>{lev}</b>",
        level="critical", kind="open", dedupe_key=f"open:{s}:{int(time.time()//60)}", cooldown_sec=30
    )

async def send_trade_update(info: Dict[str, Any]) -> None:
    plan = info.get("plan") or {}
    s = plan.get("symbol", "")
    side = _fmt_side(plan.get("side", ""))
    tp = _tp_legs_to_lines(plan.get("tp"))
    sl = (plan.get("sl") or {}).get("stopPrice")
    parts = [f"📈 <b>Update</b> {s} {side}", *tp, f"🛡 SL: <code>{_fmt_num(sl,4)}</code>"]
    await notify_telegram("\n".join(parts), level="warning", kind="status", dedupe_key=f"upd:{s}:{hashlib.sha1(json.dumps(plan, sort_keys=True, default=str).encode()).hexdigest()[:8]}", cooldown_sec=45)

async def send_trade_closed(info: Dict[str, Any]) -> None:
    plan = info.get("plan") or {}
    s = (plan.get("symbol") or info.get("symbol") or "").upper()
    side = _fmt_side(plan.get("side", ""))
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

    from .telegram_notifier_core import _fmt_pct_prob, _fmt_usd
    lines = [f"🔴 <b>Closed</b> · <b>{kind}</b> · {s} {side}"]
    lines.append(f"💰 PnL: <b>{_fmt_usd(pnl_usd)}</b> ({_fmt_pct_prob(pnl_pct) if pnl_pct is not None else '—'})")
    lines.append(f"🎯 Hit: {', '.join(hit) if hit else '—'}")
    lines.append(f"⏱ Duration: {dur if dur is not None else '—'}")
    lines.append(f"↔️ Prices: entry <code>{_fmt_num(entry,4)}</code> → exit <code>{_fmt_num(exit,4)}</code>")
    if went:
        lines.append("✅ Went well:")
        for x in went[:5]:
            lines.append(f"  • {x}")
    if bad:
        lines.append("⚠️ To improve:")
        for x in bad[:5]:
            lines.append(f"  • {x}")
    if scores:
        lines.append("🧪 Scores:")
        for k, v in scores.items():
            try:
                lines.append(f"  • {k}: {int(float(v))}/10")
            except Exception:
                lines.append(f"  • {k}: —")
    if overal is not None:
        try:
            lines.append(f"🏁 Overall: <b>{int(float(overal))}/10</b>")
        except Exception:
            pass
    await notify_telegram("\n".join(lines), level="critical", kind="close", dedupe_key=f"close:{s}:{int(time.time()//60)}", cooldown_sec=30)

# ===================== Change Tickets (re-exports) =====================
from .telegram_notifier_core import (
    format_change_approval_he, send_change_approval_he, route_change_ticket,
    send_ops_digest_now, send_eod_report_now, ensure_ops_schedulers_started,
)

# ===================== Public API =====================
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
    "make_callback", "verify_callback_data", "TelegramNotifier",
    "build_ticket_buttons",
    # חדש:
    "notify_telegram", "notify_telegram_with_markup", "should_notify",
    "_send",
]







