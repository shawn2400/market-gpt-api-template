# routes/alerts.py
import binascii, hashlib, hmac, os, json, logging, time
from typing import Optional, Dict, Any, Tuple, List
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
import httpx

logger = logging.getLogger("algogpt.alerts")
router = APIRouter(prefix="/alerts", tags=["alerts"])

# ---------- Optional Redis ----------
try:
    import redis.asyncio as aioredis  # type: ignore
except Exception:
    aioredis = None  # type: ignore

REDIS_URL = os.getenv("REDIS_URL", "")
NS = os.getenv("REDIS_NAMESPACE", "algogpt-alerts").strip() or "algogpt-alerts"

def _rkey(trade_id: str) -> str:
    return f"{NS}:trade:{trade_id}"

async def _redis():
    if not (aioredis and REDIS_URL):
        return None
    return aioredis.from_url(REDIS_URL, decode_responses=True)

# זיכרון בתהליך כגיבוי
_TRADES_MEM: Dict[str, Dict[str, Any]] = {}

async def _store_trade(trade: Dict[str, Any]) -> None:
    trade_id = trade["trade_id"]
    r = await _redis()
    if r:
        await r.set(_rkey(trade_id), json.dumps(trade, separators=(",", ":")))
    _TRADES_MEM[trade_id] = trade

async def _load_trade(trade_id: str) -> Optional[Dict[str, Any]]:
    if trade_id in _TRADES_MEM:
        return _TRADES_MEM[trade_id]
    r = await _redis()
    if r:
        raw = await r.get(_rkey(trade_id))
        if raw:
            try:
                t = json.loads(raw)
                _TRADES_MEM[trade_id] = t
                return t
            except Exception:
                return None
    return None

async def _update_trade(trade_id: str, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    t = await _load_trade(trade_id)
    if not t:
        return None
    t.update(updates)
    await _store_trade(t)
    return t

# ---------- HMAC ----------
def _get_secret_bytes() -> Optional[bytes]:
    secret = os.getenv("ALERTS_INGEST_HMAC_SECRET") or os.getenv("WEBHOOK_HMAC_SECRET") or ""
    if not secret:
        return None
    is_hex = os.getenv("ALERTS_INGEST_HMAC_KEY_IS_HEX","0").lower() in ("1","true","yes","on")
    try:
        return binascii.unhexlify(secret.strip()) if is_hex else secret.encode()
    except Exception:
        return None

def _server_hexdigest(raw: bytes) -> Optional[str]:
    key = _get_secret_bytes()
    if not key:
        return None
    return hmac.new(key, raw, hashlib.sha256).hexdigest()

def _client_hexdigest_from_headers(request: Request) -> Optional[str]:
    hv = request.headers.get("x-webhook-hmac") or request.headers.get("X-Webhook-Hmac")
    if not hv:
        hv = request.headers.get("x-hub-signature-256") or request.headers.get("X-Hub-Signature-256")
        if hv and hv.startswith("sha256="):
            hv = hv.split("=",1)[1]
    if not hv:
        return None
    hv = hv.strip().lower()
    return hv if len(hv) == 64 else None

# ---------- Alt auth (fallbacks) ----------
def _safe_eq(a: Optional[str], b: Optional[str]) -> bool:
    if not a or not b:
        return False
    try:
        return hmac.compare_digest(a.strip(), b.strip())
    except Exception:
        return a.strip() == b.strip()

def _alt_auth_ok(request: Request) -> bool:
    """
    מאפשר אימות אלטרנטיבי אם אין/לא תקין HMAC:
    - x-api-key == $API_KEY או $API_TOKEN או $PRIMARY_API_TOKEN
    - Authorization: Bearer == $API_BEARER_TOKEN
    - או אם ALLOW_ALERTS_INGEST_NO_HMAC=1 (בייפאס מבוקר)
    """
    allow_no_hmac = (os.getenv("ALLOW_ALERTS_INGEST_NO_HMAC","0").lower() in ("1","true","yes","on"))

    if allow_no_hmac:
        return True

    hdr_key = request.headers.get("x-api-key") or request.headers.get("X-Api-Key") or ""
    bearer  = request.headers.get("authorization") or request.headers.get("Authorization") or ""
    if bearer.lower().startswith("bearer "):
        bearer = bearer.split(" ",1)[1].strip()

    env_keys: List[str] = [
        os.getenv("API_KEY",""),
        os.getenv("API_TOKEN",""),
        os.getenv("PRIMARY_API_TOKEN",""),
    ]
    env_bearer = os.getenv("API_BEARER_TOKEN","")

    if hdr_key and any(_safe_eq(hdr_key, ek) for ek in env_keys if ek):
        return True
    if bearer and env_bearer and _safe_eq(bearer, env_bearer):
        return True

    return False

# ---------- Telegram ----------
def _bool(v, default=False) -> bool:
    if isinstance(v, bool): return v
    s = str(v).strip().lower()
    if s in ("1","true","yes","on"): return True
    if s in ("0","false","no","off"): return False
    return bool(default)

def _fmt_money(v) -> str:
    try:
        return f"${float(v):.2f}"
    except Exception:
        return str(v)

async def _tg_send(text: str) -> bool:
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id   = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if not bot_token or not chat_id:
        return False
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    try:
        async with httpx.AsyncClient(timeout=10.0) as cli:
            r = await cli.post(url, json={
                "chat_id": int(chat_id) if chat_id.isdigit() else chat_id,
                "text": text,
                "parse_mode": "Markdown",
                "disable_web_page_preview": True
            })
        return r.status_code == 200
    except Exception as e:
        logger.warning("telegram send failed: %s", e)
        return False

def _md_escape(s: str) -> str:
    return str(s).replace("_","\\_").replace("*","\\*").replace("[","\\[").replace("`","\\`")

def _compose_new_trade_msg(t: Dict[str, Any], approve_url: Optional[str], reject_url: Optional[str]) -> str:
    sym = _md_escape(t["symbol"])
    lines = [
        "📈 *New Trade Signal*",
        f"• Symbol: `{sym}`",
        f"• Side: `{t.get('side','?')}`   Market: `{t.get('market','futures')}`",
        f"• Qty: `{t.get('qty','?')}`   Lev: `{t.get('leverage','?')}`",
        f"• Score: `{t.get('score','?')}`",
    ]
    if t.get("eta_open_min") is not None:
        lines.append(f"• ETA Open: `{t['eta_open_min']}m`")
    if t.get("tp1") is not None:
        lines.append(f"• TP1: `{t['tp1']}`  ETA:`{t.get('eta_tp1_min','?')}m`  P(s):`{t.get('prob_tp1_pct','?')}%`")
    if t.get("tp2") is not None:
        lines.append(f"• TP2: `{t['tp2']}`  ETA:`{t.get('eta_tp2_min','?')}m`  P(s):`{t.get('prob_tp2_pct','?')}%`")
    if t.get("tp3") is not None:
        lines.append(f"• TP3: `{t['tp3']}`  ETA:`{t.get('eta_tp3_min','?')}m`  P(s):`{t.get('prob_tp3_pct','?')}%`")
    if t.get("sl") is not None:
        lines.append(f"• SL: `{t['sl']}`")
    if t.get("prob_overall_pct") is not None:
        lines.append(f"• Success %: `{t['prob_overall_pct']}%`")
    if t.get("expiry_ts"):
        lines.append(f"• Expires: `{t['expiry_ts']}`")
    if t.get("reason"):
        lines.append(f"• Reason: { _md_escape(t['reason']) }")
    lines.append(f"• Require Approval: `{t.get('require_approval', True)}`")
    if t.get("trade_id"):
        lines.append(f"• Trade: `{t['trade_id']}`")
    if approve_url and reject_url:
        lines += [f"✅ {approve_url}", f"❌ {reject_url}"]
    return "\n".join(lines)

def _compose_change_msg(trade: Dict[str,Any], what: str, details: str) -> str:
    sym = _md_escape(trade["symbol"])
    return "\n".join([
        f"🔔 *Update* — `{sym}`",
        f"• {what}: {details}",
        f"• Trade: `{trade.get('trade_id','?')}`",
    ])

def _compose_hit_msg(trade: Dict[str,Any], target: str, price: Any) -> str:
    sym = _md_escape(trade["symbol"])
    return "\n".join([
        f"🎯 *{target} HIT* — `{sym}`",
        f"• Price: `{price}`",
        f"• Trade: `{trade.get('trade_id','?')}`",
    ])

def _compose_final_report(trade: Dict[str,Any]) -> str:
    sym = _md_escape(trade["symbol"])
    lines = [
        f"📄 *Final Report* — `{sym}`",
        f"• Side: `{trade.get('side','?')}`   Qty: `{trade.get('qty','?')}`   Lev: `{trade.get('leverage','?')}`",
        f"• Score Final: `{trade.get('final_score','?')}`",
    ]
    if trade.get("pnl_usd") is not None or trade.get("pnl_pct") is not None:
        lines.append(f"• PnL: `{_fmt_money(trade.get('pnl_usd'))}`  (`{trade.get('pnl_pct','?')}%`)")
    for key in ("tp1_usd","tp2_usd","tp3_usd","sl_usd"):
        if trade.get(key) is not None:
            label = key.upper().replace("_USD","")
            lines.append(f"• {label}: `{_fmt_money(trade[key])}`")
    if trade.get("management_summary"):
        lines.append(f"• Management: { _md_escape(trade['management_summary']) }")
    if trade.get("improvement_suggestion"):
        lines.append(f"• Improve: { _md_escape(trade['improvement_suggestion']) }")
    if trade.get("expiry_ts"):
        lines.append(f"• Expiry: `{trade['expiry_ts']}`")
    return "\n".join(lines)

# ---------- Helpers: normalize payload ----------
def _mk_trade_from_payload(p: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
    trade_id = p.get("trade_id") or p.get("ticket_id") or f"T_{int(time.time()*1000)}"
    trade: Dict[str, Any] = {
        "trade_id": trade_id,
        "symbol":   str(p.get("symbol","")).upper(),
        "market":   str(p.get("market","futures")).lower(),
        "side":     str(p.get("side","")).upper(),        # BUY/SELL
        "qty":      float(p.get("qty", 0) or p.get("quantity", 0)),
        "leverage": int((p.get("leverage") or p.get("lev") or 0)),
        "score":    float(p.get("score") or 0),
        "reason":   str(p.get("reason", "")),
        "require_approval": _bool(p.get("require_approval", True)),
        "created_ts": int(time.time()),
        "eta_open_min":  p.get("eta_open_min"),
        "eta_tp1_min":   p.get("eta_tp1_min"),
        "eta_tp2_min":   p.get("eta_tp2_min"),
        "eta_tp3_min":   p.get("eta_tp3_min"),
        "tp1": p.get("tp1"), "tp2": p.get("tp2"), "tp3": p.get("tp3"),
        "sl":  p.get("sl"),
        "prob_overall_pct": p.get("prob_overall_pct"),
        "prob_tp1_pct":     p.get("prob_tp1_pct"),
        "prob_tp2_pct":     p.get("prob_tp2_pct"),
        "prob_tp3_pct":     p.get("prob_tp3_pct"),
        "expiry_ts": p.get("expiry_ts"),
        "status": "pending",  # pending/open/closed
        "hits": {"tp1": False, "tp2": False, "tp3": False, "sl": False},
        "history": [],
    }
    return trade_id, trade

# ================== ROUTES ==================

@router.get("/ping")
async def ping():
    return {"ok": True, "service": "alerts"}

@router.post("/_debug/alerts-hmac-check")
async def debug_hmac_check(request: Request):
    raw = await request.body()
    calc = _server_hexdigest(raw)
    if not calc:
        return JSONResponse(status_code=500, content={"ok": False, "error": "server_hmac_misconfigured", "body_len": len(raw)})
    return {"ok": True, "server_hex": calc, "body_len": len(raw)}

# אליאס תואם-לאחור ל/alerts/analysis (אם מישהו עדיין פונה לשם)
@router.post("/analysis")
async def analysis_alias(request: Request):
    return await ingest(request)

@router.post("/ingest")
async def ingest(request: Request):
    raw = await request.body()

    # 1) ניסיון HMAC מלא
    server_hex = _server_hexdigest(raw)
    client_hex = _client_hexdigest_from_headers(request)

    if server_hex and client_hex and hmac.compare_digest(client_hex, server_hex):
        hmac_ok = True
    else:
        hmac_ok = False

    # 2) Fallback: API key / Bearer / בייפאס ENV
    if not hmac_ok:
        if _alt_auth_ok(request):
            auth_mode = "fallback"
        else:
            if not client_hex:
                return JSONResponse(status_code=401, content={"ok": False, "error": "missing_hmac_header"})
            return JSONResponse(status_code=401, content={"ok": False, "error": "invalid_hmac_signature"})
    else:
        auth_mode = "hmac"

    # Parse JSON
    try:
        payload = json.loads(raw.decode("utf-8"))
    except Exception:
        return JSONResponse(status_code=400, content={"ok": False, "error": "invalid_json"})

    trade_id, trade = _mk_trade_from_payload(payload)
    if not trade["symbol"] or not trade["side"] or trade["qty"] <= 0 or trade["leverage"] <= 0:
        return JSONResponse(status_code=400, content={"ok": False, "error": "bad_trade_params"})

    await _store_trade(trade)

    executed_result: Optional[Dict[str, Any]] = None
    if not trade["require_approval"]:
        trade["status"] = "open"
        await _store_trade(trade)
        # כאן אפשר להפעיל ביצוע אמיתי אם רלוונטי

    public_host = (os.getenv("PUBLIC_HOST","") or os.getenv("WEBHOOK_HOST","")).rstrip("/")
    approve_url = reject_url = None
    if public_host:
        approve_url = f"{public_host}/ops/approve?ticket_id={trade_id}"
        reject_url  = f"{public_host}/ops/reject?ticket_id={trade_id}"

    msg = _compose_new_trade_msg(
        trade,
        approve_url if trade["require_approval"] else None,
        reject_url  if trade["require_approval"] else None
    )
    notified = await _tg_send(msg)

    resp: Dict[str, Any] = {
        "ok": True,
        "accepted": True,
        "trade_id": trade_id,
        "notified": {"telegram": notified},
        "auth_mode": auth_mode,
    }
    if executed_result is not None:
        resp["executed"] = executed_result
    return resp

@router.post("/trades/update")
async def trades_update(request: Request):
    try:
        upd = json.loads((await request.body()).decode("utf-8"))
    except Exception:
        return JSONResponse(status_code=400, content={"ok": False, "error": "invalid_json"})

    trade_id = str(upd.get("trade_id") or "")
    if not trade_id:
        return JSONResponse(status_code=400, content={"ok": False, "error": "missing_trade_id"})

    trade = await _load_trade(trade_id)
    if not trade:
        return JSONResponse(status_code=404, content={"ok": False, "error": "trade_not_found"})

    events: List[str] = []

    for key in ("sl","tp1","tp2","tp3"):
        if key in upd and upd[key] is not None and upd[key] != trade.get(key):
            old, new = trade.get(key), upd[key]
            await _tg_send(_compose_change_msg(trade, key.upper() + " moved", f"`{old}` → `{new}`"))
            events.append(f"moved_{key}:{old}->{new}")
            trade[key] = new

    for tgt in ("tp1","tp2","tp3","sl"):
        flag = f"{tgt}_hit"
        if _bool(upd.get(flag, False)) and not trade["hits"].get(tgt):
            trade["hits"][tgt] = True
            await _tg_send(_compose_hit_msg(trade, tgt.upper(), trade.get(tgt)))
            events.append(f"hit_{tgt}")

    if upd.get("status") in ("pending","open","closed") and upd["status"] != trade.get("status"):
        events.append(f"status:{trade.get('status')}->{upd['status']}")
        trade["status"] = upd["status"]

    for k in ("final_score","management_summary","improvement_suggestion"):
        if k in upd and upd[k] is not None:
            trade[k] = upd[k]

    for k in ("pnl_usd","pnl_pct","tp1_usd","tp2_usd","tp3_usd","sl_usd","closed_ts","expiry_ts"):
        if k in upd:
            trade[k] = upd[k]

    if events:
        trade["history"].append({"ts": int(time.time()), "events": events})

    await _store_trade(trade)

    if trade.get("status") == "closed":
        await _tg_send(_compose_final_report(trade))

    return {"ok": True, "trade": trade}































