# utils/telegram_notifier.py (Part 2/2)
from __future__ import annotations

import os, asyncio, logging, json, time
from typing import Any, Dict, Optional, List, Tuple
from datetime import datetime, timezone, timedelta

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

logger = logging.getLogger("algogpt.tg")

# ===================== Basic Ops Notifications =====================
async def notify_no_trades() -> None: return None

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

    # (פשוט עוקב אחרי ה-throttle הפנימי – לא מוסיף דקויות נוספות כאן)
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

    lines = [f"⚙️ <b>Explain Trade</b>", f"<b>{sym}</b> · <b>{side}</b> · lev=<b>{lev}</b>"]
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

async def send_trade_approval(idem: str, plan: Dict[str, Any], chat_id: Optional[int] = None) -> None:
    symbol  = str(plan.get("symbol","")).upper()
    side    = _fmt_side(str(plan.get("side","")))
    lev     = plan.get("leverage") or plan.get("lev") or "—"
    otype   = _fmt_order_type(str(plan.get("order_type") or plan.get("entry_type") or "MARKET"))
    entry   = plan.get("entry_price") or plan.get("limit_price") or plan.get("price")
    now_px  = plan.get("now_price") or _try_get_live_price(symbol)
    sl_obj  = plan.get("sl") or {}
    sl_px   = sl_obj.get("stopPrice") or sl_obj.get("price")
    tp_legs = plan.get("tp") or plan.get("tp_orders") or []
    budget  = plan.get("budget_usd") or plan.get("budget") or plan.get("budget_used")
    exp_pnl = plan.get("expected_pnl_usd") or plan.get("expected_usd") or None

    probs   = plan.get("prob") or plan.get("probs") or {}
    eta     = plan.get("eta") or {}
    eta_entry = eta.get("entry_sec") or eta.get("entry")

    reason  = plan.get("why") or plan.get("explain") or plan.get("reasons")
    why_txt = _trim_reason(reason)
    kind    = (plan.get("trade_kind") or plan.get("mode") or plan.get("market") or "Futures").capitalize()

    lines: list[str] = []
    lines.append(f"🟡 <b>Trade Pending Approval</b> · <b>{kind}</b>")
    lines.append(f"🪙 <b>{symbol}</b> · {side} · lev <b>{lev}</b> · {otype}")
    lines.append(f"💫 Now ~ <code>{_fmt_num(now_px, 4)}</code> · 🎯 Entry ~ <code>{_fmt_num(entry, 4)}</code> · ⏳ ETA entry {_fmt_eta(eta_entry)}")
    lines.append(f"🛡 SL: <code>{_fmt_num(sl_px, 4)}</code>")
    lines += _tp_legs_to_lines(tp_legs, eta=eta, probs=probs)
    overall_p = probs.get("overall") or probs.get("success") or probs.get("p_overall")
    lines.append(f"📈 Success (overall): <b>{_fmt_pct_prob(overall_p)}</b> · P(TP1): {_fmt_pct_prob(probs.get('tp1'))} · P(TP2): {_fmt_pct_prob(probs.get('tp2'))} · P(TP3): {_fmt_pct_prob(probs.get('tp3'))}")
    lines.append(f"💸 Budget: {_fmt_usd(budget)} · Expected PnL: {_fmt_usd(exp_pnl)}")
    lines.append(f"🧠 Why: {why_txt}")
    lines.append("— — —")
    lines.append(f"🕒 {_fmt_il(time.time())}")

    urls = _build_trade_urls(idem, plan)
    kb = {"inline_keyboard":[
        [{"text":"✅ Approve", "url": urls["approve"]},
         {"text":"❌ Reject",  "url": urls["reject"]}],
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
    hit     = info.get("hit") or []     # e.g. ["TP1","TP2"]
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

# ===================== Change Tickets (non-trade) =====================
def _format_change_he(change: Dict[str, Any]) -> str:
    tid = str(change.get("ticket_id","—")); ttl = int(change.get("ttl_sec", 600))
    crs = change.get("crs", "—"); sensitive = bool(change.get("sensitive", False))
    two_man = bool(change.get("two_man", False)); version = change.get("version", "—")
    plan    = change.get("plan", "—")
    budget  = change.get("budget") or {}; dollars = budget.get("dollars_max", 0.0)
    api_max = budget.get("api_calls_max", 0); tokens = budget.get("ai_tokens_max", 0)
    impact  = change.get("impact") or {}; cpu_pct = impact.get("cpu_pct", None); mem_pct = impact.get("mem_pct", None); api_rate = impact.get("api_per_min", None)
    touches = change.get("touches") or {}; t_trd = bool(touches.get("trading", False)); t_alr = bool(touches.get("alerts", False)); t_env = bool(touches.get("env", False))
    il_ts, utc_ts = _fmt_il(time.time()), datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    try: dollars_fmt = f"{float(dollars):.2f}"
    except Exception: dollars_fmt = str(dollars)
    lines: List[str] = []
    lines.append(f"<b>{_em('🕒','זמן')}</b>: {il_ts} | {utc_ts}")
    lines.append(f"<b>{_em('✅','דרוש אישור שינוי')}</b> (Change Approval)")
    lines.append(f"<b>ID</b>: <code>{tid}</code>")
    lines.append(f"<b>Two-man</b>: {'ON' if two_man else 'OFF'} | <b>TTL</b>: {ttl}s")
    lines.append(f"<b>CRS</b>: {crs}/10 | <b>Sensitive</b>: {'True' if sensitive else 'False'}")
    lines.append(f"<b>Version</b>: <code>{version}</code>")
    lines.append(f"{_em('📝','תכנית')} — {plan}")
    lines.append("— — —")
    lines.append(f"{_em('🖥️','השפעת עומס (משוער)')}: CPU {_fmt_pct(cpu_pct)}, Mem {_fmt_pct(mem_pct)}, API/דקה {_fmt_pct(api_rate)}")
    lines.append(f"{_em('💰','עלות (תקרה)')}: ${dollars_fmt} | טוקני AI: {_fmt_pct(tokens)} | קריאות API: {_fmt_pct(api_max)}")
    lines.append(f"{_em('🔌','נגיעה ברכיבים')}: Trading={'כן' if t_trd else 'לא'}, Alerts={'כן' if t_alr else 'לא'}, ENV={'כן' if t_env else 'לא'}")
    lines.append(f"{_em('🛡️','בטיחות')}: Canary={'ON' if change.get('canary',True) else 'OFF'} | Rollback={'ON' if change.get('rollback',True) else 'OFF'}")
    lines.append(_em("ℹ️", "לחיצה על \"אשר\" תפעיל Preflight → Canary → Promote → Post-verify עם ביטול/Rollback אוטומטי אם יש סטייה."))
    return "\n".join(lines)

def _format_change_en(change: Dict[str, Any]) -> str:
    il_ts, utc_ts = _fmt_il(time.time()), datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    tid = str(change.get("ticket_id","—")); ttl = int(change.get("ttl_sec", 600))
    crs = change.get("crs", "—"); sensitive = bool(change.get("sensitive", False))
    two_man = bool(change.get("two_man", False)); version = change.get("version", "—"); plan = change.get("plan", "—")
    budget = change.get("budget") or {}; dollars = budget.get("dollars_max", 0.0); api_max = budget.get("api_calls_max", 0); tokens = budget.get("ai_tokens_max", 0)
    impact = change.get("impact") or {}; cpu_pct = impact.get("cpu_pct", None); mem_pct = impact.get("mem_pct", None); api_rate = impact.get("api_per_min", None)
    try: dollars_fmt = f"{float(dollars):.2f}"
    except Exception: dollars_fmt = str(dollars)
    lines: List[str] = []
    lines.append(f"<b>{_em('🕒','Time')}</b>: {il_ts} | {utc_ts}")
    lines.append(f"<b>{_em('✅','Change Approval Required')}</b>")
    lines.append(f"<b>ID</b>: <code>{tid}</code>")
    lines.append(f"<b>Two-man</b>: {'ON' if two_man else 'OFF'} | <b>TTL</b>: {ttl}s")
    lines.append(f"<b>CRS</b>: {crs}/10 | <b>Sensitive</b>: {'True' if sensitive else 'False'}")
    lines.append(f"<b>Version</b>: <code>{version}</code>")
    lines.append(f"{_em('📝','Plan')} — {plan}")
    lines.append("— — —")
    lines.append(f"{_em('🖥️','Estimated Load Impact')}: CPU {_fmt_pct(cpu_pct)}, Mem {_fmt_pct(mem_pct)}, API/min {_fmt_pct(api_rate)}")
    lines.append(f"{_em('💰','Cost Cap')}: ${dollars_fmt} | AI tokens: {_fmt_pct(tokens)} | API calls: {_fmt_pct(api_max)}")
    lines.append(f"{_em('🔌','Touches')}: Trading={'Yes' if (change.get('touches') or {}).get('trading') else 'No'}, Alerts={'Yes' if (change.get('touches') or {}).get('alerts') else 'No'}, ENV={'Yes' if (change.get('touches') or {}).get('env') else 'No'}")
    lines.append(f"{_em('🛡️','Safety')}: Canary={'ON' if change.get('canary',True) else 'OFF'} | Rollback={'ON' if change.get('rollback',True) else 'OFF'}")
    lines.append(_em("ℹ️", 'Press "Approve" to run Preflight → Canary → Promote → Post-verify with auto rollback on deviation.'))
    return "\n".join(lines)

def _format_change_mixed(change: Dict[str, Any]) -> str:
    return _format_change_he(change) + "\n\n" + _format_change_en(change)

def format_change_approval_he(change: Dict[str, Any]) -> str:
    lang = os.getenv("OPS_APPROVAL_LANG","mix").strip().lower()
    if lang == "he":  return _format_change_he(change)
    if lang == "en":  return _format_change_en(change)
    return _format_change_mixed(change)

async def send_change_approval_he(change: Dict[str, Any], chat_id: Optional[int] = None) -> Dict[str, Any] | None:
    if not BOT_TOKEN or not API_BASE:
        logger.debug({"event":"tg.skip_send","reason":"missing_token_or_api"})
        return None
    urls = _ensure_ticket_urls(change)
    text = format_change_approval_he(change)
    kb_rows: list[list[dict[str,str]]] = []
    row1 = []
    if urls.get("approve"): row1.append({"text": "✅ אשר / Approve", "url": urls["approve"]})
    if urls.get("reject"):  row1.append({"text": "❌ דחה / Reject", "url": urls["reject"]})
    if row1: kb_rows.append(row1)
    if urls.get("ticket"):
        kb_rows.append([{"text": "🧾 פרטי הטיקט / Ticket", "url": urls["ticket"]}])
    reply_markup = {"inline_keyboard": kb_rows}
    try:
        await _tg_send_with_markup(text, reply_markup, chat_id=chat_id)
        return {"ok": True}
    except Exception as e:
        logger.warning({"event":"tg.approval_send_failed","error":str(e)})
        return {"ok": False, "error": str(e)}

# ===================== Auto-routing for change tickets =====================
def _is_very_sensitive(change: Dict[str, Any]) -> tuple[bool, str]:
    crs = float(change.get("crs", 0) or 0)
    if crs >= float(os.getenv("OPS_MANUAL_MIN_CRS","8")):
        return True, f"crs>={os.getenv('OPS_MANUAL_MIN_CRS','8')}"
    level = str(change.get("sensitive_level", "")).strip().lower()
    levels = set((os.getenv("OPS_MANUAL_SENSITIVE_LEVELS","high,critical")).split(","))
    if level and level in {x.strip().lower() for x in levels}:
        return True, f"level={level}"
    if bool(change.get("sensitive", False)):
        touches = (change.get("touches") or {})
        for t in (os.getenv("OPS_MANUAL_TOUCHES","trading,env")).split(","):
            if bool(touches.get(t.strip(), False)):
                return True, f"sensitive+touches.{t.strip()}"
    return False, ""

async def route_change_ticket(change: Dict[str, Any]) -> Dict[str, Any]:
    strict = os.getenv("OPS_APPROVAL_STRICT","1").lower() in ("1","true","yes","on")
    crs       = float(change.get("crs", 0) or 0)
    sensitive = bool(change.get("sensitive", False))
    if strict:
        manual, reason = _is_very_sensitive(change)
    else:
        manual = (sensitive or crs >= int(os.getenv("OPS_AUTO_CRS_MAX","6")))
        reason = "legacy_sensitive_or_high_crs" if manual else ""
    tid       = str(change.get("ticket_id",""))
    plan      = change.get("plan",""); version   = change.get("version","")

    if manual:
        await _store_change_event({"kind":"change","ticket_id":tid,"status":"awaiting_manual","sensitive":sensitive,"crs":crs,"plan":plan,"version":version,"reason":reason})
        await send_change_approval_he(change)
        return {"ok": True, "auto": False, "reason": reason}

    # auto-approve (שקט)
    urls = _ensure_ticket_urls(change)
    ok = False
    try:
        import httpx
        if urls.get("approve"):
            async with httpx.AsyncClient(timeout=10.0) as cli:
                r = await cli.get(urls["approve"])
                ok = (200 <= r.status_code < 300)
    except Exception as e:
        logger.warning({"event":"auto_approve.failed","error":str(e)})
    await _store_change_event({
        "kind":"change","ticket_id":tid,
        "status": "auto_approved" if ok else "auto_approve_failed",
        "sensitive": sensitive,"crs": crs,"plan": plan,"version": version,
        "reason": "strict_auto" if strict else "legacy_auto",
    })
    if not ok:
        await send_change_approval_he(change)
    return {"ok": True, "auto": True}

# ===================== Digests & EOD =====================
async def send_ops_digest_now(hours: Optional[int] = None) -> None:
    interval_h = int(hours or int(os.getenv("OPS_DIGEST_INTERVAL_HOURS","3")))
    ts_min = time.time() - interval_h * 3600
    items = await _load_changes_since(ts_min)
    if not items:
        await _tg_send(f"🧭 דיג'סט ({interval_h}ש) — אין עדכונים.\n🧭 Digest ({interval_h}h) — No updates.")
        return
    total = len(items)
    auto_ok   = sum(1 for x in items if x.get("status")=="auto_approved")
    auto_fail = sum(1 for x in items if x.get("status")=="auto_approve_failed")
    manual    = sum(1 for x in items if x.get("status")=="awaiting_manual")

    def _line(x: Dict[str,Any]) -> str:
        ts = _fmt_il(x.get("ts")); ver = x.get("version") or "—"; crs = x.get("crs","?")
        sens = "Sensitive" if x.get("sensitive") else "Non-sens"
        plan = (x.get("plan") or "—");  plan = (plan[:77] + "…") if len(plan) > 80 else plan
        return f"• {ts} · v{ver} · CRS {crs} · {sens} · {x.get('status')}\n  ↳ {plan}"

    last_lines = [_line(x) for x in items[-8:]]
    msg = [
        f"🧭 דיג'סט ({interval_h}ש) — סה\"כ {total} | Auto OK {auto_ok} | Auto Fail {auto_fail} | Manual {manual}",
        f"🧭 Digest ({interval_h}h) — total {total} | Auto OK {auto_ok} | Auto Fail {auto_fail} | Manual {manual}",
        "— — —", *last_lines
    ]
    await _tg_send("\n".join(msg))

async def send_eod_report_now() -> None:
    try:
        from zoneinfo import ZoneInfo
        tz_il = ZoneInfo("Asia/Jerusalem")
    except Exception:
        tz_il = timezone(timedelta(hours=3))
    now_il   = datetime.now(tz_il)
    start_il = now_il.replace(hour=0, minute=0, second=0, microsecond=0)
    ts_min   = start_il.astimezone(timezone.utc).timestamp()
    items    = await _load_changes_since(ts_min)
    total = len(items)
    auto_ok   = sum(1 for x in items if x.get("status")=="auto_approved")
    auto_fail = sum(1 for x in items if x.get("status")=="auto_approve_failed")
    manual    = sum(1 for x in items if x.get("status")=="awaiting_manual")

    def _short(x: Dict[str,Any]) -> str:
        ts = _fmt_il(x.get("ts")); ver = x.get("version") or "—"; crs = x.get("crs","?")
        sens = "Sensitive" if x.get("sensitive") else "Non-sens"
        plan = (x.get("plan") or "—"); plan = (plan[:97] + "…") if len(plan) > 100 else plan
        return f"• {ts} · v{ver} · CRS {crs} · {sens} · {x.get('status')} · {plan}"

    last = [_short(x) for x in items[-12:]]
    msg = [
        f"📘 דוח יומי — {now_il.strftime('%Y-%m-%d')} (IL)",
        f"סה\"כ שינויים: {total} | Auto OK: {auto_ok} | Auto Fail: {auto_fail} | Manual: {manual}",
        f"📘 End-of-Day — {now_il.strftime('%Y-%m-%d')} (IL)",
        f"Total changes: {total} | Auto OK: {auto_ok} | Auto Fail: {auto_fail} | Manual: {manual}",
        "— — —", *last
    ]
    await _tg_send("\n".join(msg))

# ===================== Schedulers =====================
_digest_task: Optional[asyncio.Task] = None
_eod_task: Optional[asyncio.Task] = None
_schedulers_started: bool = False

def _seconds_until_next_digest(now_il: Optional[datetime] = None) -> int:
    try:
        from zoneinfo import ZoneInfo
        tz_il = ZoneInfo("Asia/Jerusalem")
    except Exception:
        tz_il = timezone(timedelta(hours=3))
    now_il = now_il or datetime.now(tz_il)
    period = int(os.getenv("OPS_DIGEST_INTERVAL_HOURS","3")) * 3600
    since_midnight = now_il.hour*3600 + now_il.minute*60 + now_il.second
    rem = since_midnight % period
    wait = (period - rem) if rem != 0 else period
    return max(5, int(wait))

def _seconds_until_eod(now_il: Optional[datetime] = None) -> int:
    try:
        from zoneinfo import ZoneInfo
        tz_il = ZoneInfo("Asia/Jerusalem")
    except Exception:
        tz_il = timezone(timedelta(hours=3))
    now_il = now_il or datetime.now(tz_il)
    h = int(os.getenv("OPS_EOD_HOUR_IL","23")); m = int(os.getenv("OPS_EOD_MINUTE_IL","55"))
    target = now_il.replace(hour=h, minute=m, second=0, microsecond=0)
    if target <= now_il: target = target + timedelta(days=1)
    return max(5, int((target - now_il).total_seconds()))

async def _digest_loop() -> None:
    while True:
        try:
            await asyncio.sleep(_seconds_until_next_digest())
            await send_ops_digest_now()
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.debug({"event":"digest.loop.err","err":str(e)})
            await asyncio.sleep(5)

async def _eod_loop() -> None:
    while True:
        try:
            await asyncio.sleep(_seconds_until_eod())
            await send_eod_report_now()
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.debug({"event":"eod.loop.err","err":str(e)})
            await asyncio.sleep(5)

async def ensure_ops_schedulers_started() -> None:
    global _schedulers_started, _digest_task, _eod_task
    if _schedulers_started:
        return
    loop = asyncio.get_event_loop()
    if os.getenv("OPS_DIGEST_ENABLE","1").lower() in ("1","true","yes","on"):
        _digest_task = loop.create_task(_digest_loop())
    if os.getenv("OPS_EOD_ENABLE","1").lower() in ("1","true","yes","on"):
        _eod_task = loop.create_task(_eod_loop())
    _schedulers_started = True

# ===================== Public API =====================
__all__ = [
    # flags & simple notifiers
    "set_explain_enabled", "get_explain_enabled",
    "notify_no_trades", "notify_scan_error", "notify_explain_trade",
    "notify_sl_tp_update", "notify_info", "notify_error",
    "notify_heartbeat", "notify_daily_summary", "notify_ops_alert",
    "register_webhook",
    # trade approvals / updates
    "send_trade_approval", "send_trade_opened", "send_trade_update", "send_trade_closed",
    # change approvals
    "format_change_approval_he", "send_change_approval_he", "route_change_ticket",
    # digests
    "send_ops_digest_now", "send_eod_report_now", "ensure_ops_schedulers_started",
    # auto-approve query for routes (אם צריך מצד הרואטרים)
    "should_auto_approve_trade",
]

