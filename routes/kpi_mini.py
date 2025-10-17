# routes/kpi_mini.py
# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import json
import time
from typing import Any, Dict, List, Optional, Tuple
from contextlib import suppress

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse, HTMLResponse, PlainTextResponse

router = APIRouter(tags=["kpi-mini"])

# ---------- Redis (Valkey) soft-import ----------
try:
    import redis.asyncio as aioredis  # type: ignore
except Exception:
    aioredis = None  # type: ignore

REDIS_URL = (os.getenv("REDIS_URL") or os.getenv("VALKEY_URL") or "").strip()
NS = (os.getenv("REDIS_NAMESPACE") or "algogpt").strip()
KPI_PREFIX = f"{NS}:kpi"

# Windows to expose (comma list), e.g. "1d,7d,30d"
KPI_WINDOWS = [w.strip() for w in (os.getenv("KPI_WINDOWS") or "1d,7d,30d").split(",") if w.strip()]

# ---------- Telegram soft utils ----------
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
ADMIN_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID") or os.getenv("ADMIN_CHAT_ID")


async def _get_redis():
    if not (aioredis and REDIS_URL):
        return None
    r = getattr(router, "_redis", None)
    if r:
        return r
    r = aioredis.from_url(REDIS_URL, decode_responses=True)
    router._redis = r  # type: ignore[attr-defined]
    return r


# ---------- Helpers ----------
def _pct(n: float, d: float) -> float:
    try:
        return (float(n) / float(max(d, 1e-12))) * 100.0
    except Exception:
        return 0.0


def _hgetf(h: Dict[str, Any], k: str, default: float = 0.0) -> float:
    try:
        v = h.get(k)
        return float(v) if v is not None else default
    except Exception:
        return default


def _hgeti(h: Dict[str, Any], k: str, default: int = 0) -> int:
    try:
        v = h.get(k)
        return int(v) if v is not None else default
    except Exception:
        return default


async def _hgetall_safe(r, key: str) -> Dict[str, Any]:
    """
    Read a hash and return dict[str, str]; on any failure return {}.
    """
    if not r:
        return {}
    try:
        d = await r.hgetall(key)
        return d or {}
    except Exception:
        return {}


def _fmt_ts(ts: int) -> str:
    # YYYY-MM-DD HH:MM:SSZ
    try:
        return time.strftime("%Y-%m-%d %H:%M:%SZ", time.gmtime(int(ts)))
    except Exception:
        return ""


# ---------- Key names (no by_symbol) ----------
def k_pnl(window: str) -> str:
    return f"{KPI_PREFIX}:pnl:roll:{window}"

def k_exec_latency(window: str) -> str:
    return f"{KPI_PREFIX}:exec:latency:{window}"

def k_binance_err(window: str) -> str:
    return f"{KPI_PREFIX}:exec:binance:err:{window}"

def k_binance_throttle(window: str) -> str:
    return f"{KPI_PREFIX}:exec:binance:throttle:{window}"

def k_redis_rtt(window: str) -> str:
    return f"{KPI_PREFIX}:infra:redis:rtt:{window}"

def k_redis_err(window: str) -> str:
    return f"{KPI_PREFIX}:infra:redis:err:{window}"

def k_regime_mix(window: str) -> str:
    return f"{KPI_PREFIX}:regime:atr_mix:{window}"

def k_session_mix(window: str) -> str:
    return f"{KPI_PREFIX}:session:mix:{window}"

def k_extreme_pick(window: str) -> str:
    return f"{KPI_PREFIX}:profile:extreme_pick:{window}"

def k_tp_times(window: str) -> str:
    # ממוצעי זמן הגעה ל-TP1/2/3 (בדקות) + מדדים של הצלחה לכל TP
    return f"{KPI_PREFIX}:tp:times:{window}"


# ---------- Core aggregation ----------
async def _collect_for_window(r, window: str) -> Dict[str, Any]:
    # PnL & trade counts
    pnl_h = await _hgetall_safe(r, k_pnl(window))
    pnl_sum = _hgetf(pnl_h, "sum", 0.0)
    trade_count = _hgeti(pnl_h, "count", 0)
    wins = _hgeti(pnl_h, "wins", 0)
    losses = _hgeti(pnl_h, "losses", 0)
    avg_r = _hgetf(pnl_h, "avg_R", 0.0)
    max_dd = _hgetf(pnl_h, "max_drawdown", 0.0)  # שלילי

    winrate = _pct(wins, wins + losses) if (wins + losses) > 0 else 0.0
    pnl_avg = (pnl_sum / trade_count) if trade_count > 0 else 0.0

    # TP times + success%
    tp_h = await _hgetall_safe(r, k_tp_times(window))
    avg_t1 = _hgetf(tp_h, "avg_t1_min", 0.0)
    med_t1 = _hgetf(tp_h, "med_t1_min", 0.0)
    avg_t2 = _hgetf(tp_h, "avg_t2_min", 0.0)
    avg_t3 = _hgetf(tp_h, "avg_t3_min", 0.0)
    t1_hit = _hgeti(tp_h, "t1_hit", 0)
    t2_hit = _hgeti(tp_h, "t2_hit", 0)
    t3_hit = _hgeti(tp_h, "t3_hit", 0)
    t_all = _hgeti(tp_h, "t_total", trade_count)
    t1_rate = _pct(t1_hit, t_all) if t_all > 0 else 0.0
    t2_rate = _pct(t2_hit, t_all) if t_all > 0 else 0.0
    t3_rate = _pct(t3_hit, t_all) if t_all > 0 else 0.0

    # Exchange errors/throttle
    be_h = await _hgetall_safe(r, k_binance_err(window))
    be_err = _hgeti(be_h, "errors", 0)
    be_total = _hgeti(be_h, "total", 0)
    be_rate = _pct(be_err, be_total) if be_total > 0 else 0.0

    bt_h = await _hgetall_safe(r, k_binance_throttle(window))
    bt_err = _hgeti(bt_h, "429", 0)
    bt_total = _hgeti(bt_h, "total", 0)
    bt_rate = _pct(bt_err, bt_total) if bt_total > 0 else 0.0

    # Exec latency
    lat_h = await _hgetall_safe(r, k_exec_latency(window))
    avg_lat = _hgetf(lat_h, "avg_ms", 0.0)
    p95_lat = _hgetf(lat_h, "p95_ms", 0.0)

    # Redis RTT / errors
    rr_h = await _hgetall_safe(r, k_redis_rtt(window))
    rr_avg = _hgetf(rr_h, "avg_ms", 0.0)
    rr_p95 = _hgetf(rr_h, "p95_ms", 0.0)
    re_h = await _hgetall_safe(r, k_redis_err(window))
    re_err = _hgeti(re_h, "errors", 0)
    re_total = _hgeti(re_h, "total", 0)
    re_rate = _pct(re_err, re_total) if re_total > 0 else 0.0

    # Regime mix
    rm_h = await _hgetall_safe(r, k_regime_mix(window))
    total_rm = _hgeti(rm_h, "total", 0)
    calm = _pct(_hgeti(rm_h, "CALM", 0), total_rm) if total_rm > 0 else 0.0
    trend = _pct(_hgeti(rm_h, "TREND", 0), total_rm) if total_rm > 0 else 0.0
    vol = _pct(_hgeti(rm_h, "VOL", 0), total_rm) if total_rm > 0 else 0.0

    # Session mix
    sm_h = await _hgetall_safe(r, k_session_mix(window))
    total_sm = _hgeti(sm_h, "total", 0)
    asia = _pct(_hgeti(sm_h, "ASIA", 0), total_sm) if total_sm > 0 else 0.0
    europe = _pct(_hgeti(sm_h, "EUROPE", 0), total_sm) if total_sm > 0 else 0.0
    us = _pct(_hgeti(sm_h, "US", 0), total_sm) if total_sm > 0 else 0.0
    other = _pct(_hgeti(sm_h, "OTHER", 0), total_sm) if total_sm > 0 else 0.0

    # Extreme pick
    ep_h = await _hgetall_safe(r, k_extreme_pick(window))
    ep_ext = _hgeti(ep_h, "extreme", 0)
    ep_total = _hgeti(ep_h, "total", 0)
    ep_rate = _pct(ep_ext, ep_total) if ep_total > 0 else 0.0

    return {
        "pnl_sum": round(pnl_sum, 4),
        "pnl_avg": round(pnl_avg, 4),
        "winrate_pct": round(winrate, 2),
        "avg_R": round(avg_r, 4),
        "avg_time_to_tp1_min": round(avg_t1, 2),
        "median_time_to_tp1_min": round(med_t1, 2),
        "avg_time_to_tp2_min": round(avg_t2, 2),
        "avg_time_to_tp3_min": round(avg_t3, 2),
        "tp1_success_pct": round(t1_rate, 2),
        "tp2_success_pct": round(t2_rate, 2),
        "tp3_success_pct": round(t3_rate, 2),
        "max_drawdown": round(max_dd, 4),
        "trade_count": int(trade_count),
        "win_count": int(wins),
        "loss_count": int(losses),
        "binance_err_rate_pct": round(be_rate, 3),
        "binance_throttle_rate_pct": round(bt_rate, 3),
        "avg_order_latency_ms": round(avg_lat, 2),
        "p95_order_latency_ms": round(p95_lat, 2),
        "redis_rtt_ms": round(rr_avg, 2),
        "p95_redis_rtt_ms": round(rr_p95, 2),
        "redis_errors_rate_pct": round(re_rate, 3),
        "atr_regime_mix_pct": {"CALM": round(calm, 2), "TREND": round(trend, 2), "VOL": round(vol, 2)},
        "session_mix_pct": {"ASIA": round(asia, 2), "EUROPE": round(europe, 2), "US": round(us, 2), "OTHER": round(other, 2)},
        "extreme_pick_rate_pct": round(ep_rate, 2),
    }


async def _collect_all() -> Dict[str, Any]:
    r = await _get_redis()
    out: Dict[str, Any] = {"ok": True, "as_of": int(time.time()), "windows": KPI_WINDOWS, "global": {}}
    for w in KPI_WINDOWS:
        with suppress(Exception):
            out["global"][w] = await _collect_for_window(r, w)
    return out


# ---------- Telegram formatting ----------
async def _send_telegram(text: str) -> Dict[str, Any]:
    if not (TELEGRAM_BOT_TOKEN and ADMIN_CHAT_ID):
        return {"ok": False, "skipped": True, "reason": "tg_not_configured"}

    import httpx
    try:
        chat_id: Any = int(ADMIN_CHAT_ID) if str(ADMIN_CHAT_ID).isdigit() else ADMIN_CHAT_ID
    except Exception:
        chat_id = ADMIN_CHAT_ID

    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True}
    async with httpx.AsyncClient(timeout=10.0) as cli:
        r = await cli.post(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage", json=payload)
        try:
            data = r.json()
        except Exception:
            data = {}
        return {"ok": bool(data.get("ok")), "status": r.status_code, "result": data.get("result"), "raw": data}


def _fmt_line_emoji(label_he_en: str, value: str, icon: str) -> str:
    return f"{icon} <b>{label_he_en}</b>: <code>{value}</code>"

def _fmt_mini_html(as_of: int, glb: Dict[str, Dict[str, Any]]) -> str:
    # צבעים עם אמוג’י; טקסט he/en; מציג חלון 1d כברירת־מחדל אם קיים
    preferred = "1d" if "1d" in glb else (list(glb.keys())[0] if glb else "")
    g = glb.get(preferred, {})
    ts = _fmt_ts(as_of)
    rows = []

    rows.append(_fmt_line_emoji("זמן/Time", ts, "🕒"))
    rows.append(_fmt_line_emoji("PnL Σ", f"{g.get('pnl_sum',0):.2f}", "💰"))
    rows.append(_fmt_line_emoji("Winrate", f"{g.get('winrate_pct',0):.2f}%", "🎯"))
    rows.append(_fmt_line_emoji("Avg R", f"{g.get('avg_R',0):.2f}", "📈"))
    rows.append(_fmt_line_emoji("TP1 ⏱ avg", f"{g.get('avg_time_to_tp1_min',0):.1f}m", "⏳"))
    rows.append(_fmt_line_emoji("TP1 ✅", f"{g.get('tp1_success_pct',0):.1f}%", "✅"))
    rows.append(_fmt_line_emoji("TP2 ✅", f"{g.get('tp2_success_pct',0):.1f}%", "🟩"))
    rows.append(_fmt_line_emoji("TP3 ✅", f"{g.get('tp3_success_pct',0):.1f}%", "🟦"))
    rows.append(_fmt_line_emoji("Max DD", f"{g.get('max_drawdown',0):.2f}", "📉"))
    rows.append(_fmt_line_emoji("Trades", str(g.get('trade_count',0)), "🔢"))
    rows.append(_fmt_line_emoji("Binance err", f"{g.get('binance_err_rate_pct',0):.2f}%", "⚠️"))
    rows.append(_fmt_line_emoji("Order p95", f"{g.get('p95_order_latency_ms',0):.0f}ms", "🚀"))
    rows.append(_fmt_line_emoji("Redis p95", f"{g.get('p95_redis_rtt_ms',0):.1f}ms", "🧠"))
    rows.append(_fmt_line_emoji("Regime", f"CALM {g.get('atr_regime_mix_pct',{}).get('CALM',0):.0f}% · TREND {g.get('atr_regime_mix_pct',{}).get('TREND',0):.0f}% · VOL {g.get('atr_regime_mix_pct',{}).get('VOL',0):.0f}%", "🌡️"))
    rows.append(_fmt_line_emoji("Session", f"ASIA {g.get('session_mix_pct',{}).get('ASIA',0):.0f}% · EU {g.get('session_mix_pct',{}).get('EUROPE',0):.0f}% · US {g.get('session_mix_pct',{}).get('US',0):.0f}%", "🕰️"))
    rows.append(_fmt_line_emoji("EXTREME pick", f"{g.get('extreme_pick_rate_pct',0):.0f}%", "🔥"))

    body = "<br/>".join(rows)
    title = f"📊 KPI Mini ({preferred})"
    return f"<!doctype html><meta charset='utf-8'><body style='font-family:system-ui,Arial,sans-serif;max-width:720px;margin:2rem auto;line-height:1.55'><h3 style='margin:.2rem 0 1rem'>{title}</h3><div style='font-size:1.05rem'>{body}</div></body>"


def _fmt_shell(glb: Dict[str, Dict[str, Any]], as_of: int) -> str:
    preferred = "1d" if "1d" in glb else (list(glb.keys())[0] if glb else "")
    g = glb.get(preferred, {})
    ts = _fmt_ts(as_of)
    lines = [
        f"[{ts}] KPI Mini ({preferred})",
        f"💰 PnL Σ: {g.get('pnl_sum',0):.2f} | 🎯 Winrate: {g.get('winrate_pct',0):.2f}% | 📈 Avg R: {g.get('avg_R',0):.2f}",
        f"⏳ TP1 avg: {g.get('avg_time_to_tp1_min',0):.1f}m | ✅ TP1%: {g.get('tp1_success_pct',0):.1f}% | 🟩 TP2%: {g.get('tp2_success_pct',0):.1f}% | 🟦 TP3%: {g.get('tp3_success_pct',0):.1f}%",
        f"📉 MaxDD: {g.get('max_drawdown',0):.2f} | 🔢 Trades: {g.get('trade_count',0)}",
        f"⚠️ Binance err: {g.get('binance_err_rate_pct',0):.2f}% | 🚀 Order p95: {g.get('p95_order_latency_ms',0):.0f}ms | 🧠 Redis p95: {g.get('p95_redis_rtt_ms',0):.1f}ms",
        "🌡️ Regime: CALM {c:.0f}% · TREND {t:.0f}% · VOL {v:.0f}%".format(
            c=g.get('atr_regime_mix_pct', {}).get('CALM', 0.0),
            t=g.get('atr_regime_mix_pct', {}).get('TREND', 0.0),
            v=g.get('atr_regime_mix_pct', {}).get('VOL', 0.0),
        ),
        "🕰️ Session: ASIA {a:.0f}% · EU {e:.0f}% · US {u:.0f}%".format(
            a=g.get('session_mix_pct', {}).get('ASIA', 0.0),
            e=g.get('session_mix_pct', {}).get('EUROPE', 0.0),
            u=g.get('session_mix_pct', {}).get('US', 0.0),
        ),
        f"🔥 EXTREME pick: {g.get('extreme_pick_rate_pct',0):.0f}%",
    ]
    return "\n".join(lines)


def _fmt_tg(glb: Dict[str, Dict[str, Any]], as_of: int) -> str:
    # בדיוק כמו ה־HTML אבל בשורות טלגרם
    preferred = "1d" if "1d" in glb else (list(glb.keys())[0] if glb else "")
    g = glb.get(preferred, {})
    ts = _fmt_ts(as_of)
    parts = [
        f"📊 <b>KPI Mini</b> ({preferred})",
        f"🕒 <b>Time</b>: <code>{ts}</code>",
        f"💰 <b>PnL Σ</b>: <code>{g.get('pnl_sum',0):.2f}</code>",
        f"🎯 <b>Winrate</b>: <code>{g.get('winrate_pct',0):.2f}%</code> · 📈 <b>Avg R</b>: <code>{g.get('avg_R',0):.2f}</code>",
        f"⏳ <b>TP1 avg</b>: <code>{g.get('avg_time_to_tp1_min',0):.1f}m</code> · ✅ <b>TP1%</b>: <code>{g.get('tp1_success_pct',0):.1f}%</code>",
        f"🟩 <b>TP2%</b>: <code>{g.get('tp2_success_pct',0):.1f}%</code> · 🟦 <b>TP3%</b>: <code>{g.get('tp3_success_pct',0):.1f}%</code>",
        f"📉 <b>Max DD</b>: <code>{g.get('max_drawdown',0):.2f}</code> · 🔢 <b>Trades</b>: <code>{g.get('trade_count',0)}</code>",
        f"⚠️ <b>Binance err</b>: <code>{g.get('binance_err_rate_pct',0):.2f}%</code> · 🚀 <b>Order p95</b>: <code>{g.get('p95_order_latency_ms',0):.0f}ms</code> · 🧠 <b>Redis p95</b>: <code>{g.get('p95_redis_rtt_ms',0):.1f}ms</code>",
        "🌡️ <b>Regime</b>: <code>CALM {c:.0f}% · TREND {t:.0f}% · VOL {v:.0f}%</code>".format(
            c=g.get('atr_regime_mix_pct', {}).get('CALM', 0.0),
            t=g.get('atr_regime_mix_pct', {}).get('TREND', 0.0),
            v=g.get('atr_regime_mix_pct', {}).get('VOL', 0.0),
        ),
        "🕰️ <b>Session</b>: <code>ASIA {a:.0f}% · EU {e:.0f}% · US {u:.0f}%</code>".format(
            a=g.get('session_mix_pct', {}).get('ASIA', 0.0),
            e=g.get('session_mix_pct', {}).get('EUROPE', 0.0),
            u=g.get('session_mix_pct', {}).get('US', 0.0),
        ),
        f"🔥 <b>EXTREME pick</b>: <code>{g.get('extreme_pick_rate_pct',0):.0f}%</code>",
    ]
    return "\n".join(parts)


# ---------- Routes ----------
@router.get("/ops/mini.json")
async def mini_json(send_tg: int = Query(0, ge=0, le=1)):
    data = await _collect_all()
    if send_tg == 1:
        with suppress(Exception):
            text = _fmt_tg(data.get("global", {}), data.get("as_of", int(time.time())))
            tg_res = await _send_telegram(text)
            data["telegram"] = tg_res
    return JSONResponse(data)


@router.get("/ops/mini")
async def mini_html(send_tg: int = Query(0, ge=0, le=1)):
    data = await _collect_all()
    html = _fmt_mini_html(data.get("as_of", int(time.time())), data.get("global", {}))
    if send_tg == 1:
        with suppress(Exception):
            text = _fmt_tg(data.get("global", {}), data.get("as_of", int(time.time())))
            await _send_telegram(text)
    return HTMLResponse(html)


@router.get("/ops/mini.txt")
async def mini_txt(send_tg: int = Query(0, ge=0, le=1)):
    data = await _collect_all()
    txt = _fmt_shell(data.get("global", {}), data.get("as_of", int(time.time())))
    if send_tg == 1:
        with suppress(Exception):
            tg_text = _fmt_tg(data.get("global", {}), data.get("as_of", int(time.time())))
            await _send_telegram(tg_text)
    return PlainTextResponse(txt)
