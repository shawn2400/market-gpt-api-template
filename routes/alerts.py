# routes/alerts.py
import binascii, hashlib, hmac, os, json, logging, time
from typing import Optional, Dict, Any, Tuple
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
    # הודעת פתיחה עשירה עם כל הפרטים
    sym = _md_escape(t["symbol"])
    lines = [
        "📈 *New Trade Signal*",
        f"• Symbol: `{sym}`",
        f"• Side: `{t.get('side','?')}`   Market: `{t.get('market','futures')}`",
        f"• Qty: `{t.get('qty','?')}`   Lev: `{t.get('leverage','?')}`",
        f"• Score: `{t.get('score','?')}`",
    ]
    # ETAs
    if t.get("eta_open_min") is not None:
        lines.append(f"• ETA Open: `{t['eta_open_min']}m`")
    # Targets
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
    # כפתורים
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
    # רווח/הפסד כולל
    if trade.get("pnl_usd") is not None or trade.get("pnl_pct") is not None:
        lines.append(f"• PnL: `{_fmt_money(trade.get('pnl_usd'))}`  (`{trade.get('pnl_pct','?')}%`)")
    # פירוט TPs / SL בדולרים (אם נשלח)
    for key in ("tp1_usd","tp2_usd","tp3_usd","sl_usd"):
        if trade.get(key) is not None:
            label = key.upper().replace("_USD","")
            lines.append(f"• {label}: `{_fmt_money(trade[key])}`")
    # ניהול ושיפור
    if trade.get("management_summary"):
        lines.append(f"• Management: { _md_escape(trade['management_summary']) }")
    if trade.get("improvement_suggestion"):
        lines.append(f"• Improve: { _md_escape(trade['improvement_suggestion']) }")
    # תוקף
    if trade.get("expiry_ts"):
        lines.append(f"• Expiry: `{trade['expiry_ts']}`")
    return "\n".join(lines)

# ---------- Helpers: normalize payload ----------
def _mk_trade_from_payload(p: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
    """
    יוצר מבנה טרייד “עשיר” עם שדות אופציונליים.
    מחזיר (trade_id, trade_dict)
    """
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
        # ETAs (בדקות) — אופציונלי
        "eta_open_min":  p.get("eta_open_min"),
        "eta_tp1_min":   p.get("eta_tp1_min"),
        "eta_tp2_min":   p.get("eta_tp2_min"),
        "eta_tp3_min":   p.get("eta_tp3_min"),
        # Targets
        "tp1": p.get("tp1"), "tp2": p.get("tp2"), "tp3": p.get("tp3"),
        "sl":  p.get("sl"),
        # Probabilities
        "prob_overall_pct": p.get("prob_overall_pct"),
        "prob_tp1_pct":     p.get("prob_tp1_pct"),
        "prob_tp2_pct":     p.get("prob_tp2_pct"),
        "prob_tp3_pct":     p.get("prob_tp3_pct"),
        # Expiry
        "expiry_ts": p.get("expiry_ts"),
        # runtime flags
        "status": "pending",  # pending/open/closed
        "hits": {"tp1": False, "tp2": False, "tp3": False, "sl": False},
        "history": [],  # רשימת אירועים (זמן/תאור)
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

@router.post("/ingest")
async def ingest(request: Request):
    # אימות HMAC
    raw = await request.body()
    server_hex = _server_hexdigest(raw)
    if not server_hex:
        return JSONResponse(status_code=500, content={"ok": False, "error": "server_hmac_misconfigured"})
    client_hex = _client_hexdigest_from_headers(request)
    if not client_hex:
        return JSONResponse(status_code=401, content={"ok": False, "error": "missing_hmac_header"})
    if client_hex != server_hex:
        return JSONResponse(status_code=401, content={"ok": False, "error": "Invalid HMAC signature"})

    # Parse JSON
    try:
        payload = json.loads(raw.decode("utf-8"))
    except Exception:
        return JSONResponse(status_code=400, content={"ok": False, "error": "invalid_json"})

    trade_id, trade = _mk_trade_from_payload(payload)
    if not trade["symbol"] or not trade["side"] or trade["qty"] <= 0 or trade["leverage"] <= 0:
        return JSONResponse(status_code=400, content={"ok": False, "error": "bad_trade_params"})

    # שמירה/סטטוס
    await _store_trade(trade)

    # אישור נדרש?
    executed_result: Optional[Dict[str, Any]] = None
    if not trade["require_approval"]:
        trade["status"] = "open"
        await _store_trade(trade)
        # כאן אפשר לפתוח מיידית פקודה אמיתית (אם תרצה, חבר ל-executor שלך)
        # executed_result = await _execute_real_order(trade)

    # נוטיפיקציית פתיחה לטלגרם (עם כפתורי אישור אם צריך)
    public_host = (os.getenv("PUBLIC_HOST","") or os.getenv("WEBHOOK_HOST","")).rstrip("/")
    approve_url = reject_url = None
    if public_host:
        approve_url = f"{public_host}/ops/approve?ticket_id={trade_id}"
        reject_url  = f"{public_host}/ops/reject?ticket_id={trade_id}"
    msg = _compose_new_trade_msg(trade, approve_url if trade["require_approval"] else None,
                                       reject_url if trade["require_approval"] else None)
    notified = await _tg_send(msg)

    resp: Dict[str, Any] = {"ok": True, "accepted": True, "trade_id": trade_id, "notified": {"telegram": notified}}
    if executed_result is not None:
        resp["executed"] = executed_result
    return resp

@router.post("/trades/update")
async def trades_update(request: Request):
    """
    עדכון טרייד בזמן אמת + התרעות:
    קלט JSON יכול לכלול:
    - trade_id (חובה)
    - שינויים ב: sl, tp1, tp2, tp3 (למשל הזזת SL)
    - אירועי hit: tp1_hit, tp2_hit, tp3_hit, sl_hit (boolean)
    - סטטוס: status=open/closed
    - ציון סופי: final_score
    - ניהול/שיפור: management_summary, improvement_suggestion
    - דוח סופי: pnl_usd, pnl_pct, tp1_usd, tp2_usd, tp3_usd, sl_usd, closed_ts
    """
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

    events: list[str] = []

    # שינויים ב-TP/SL
    for key in ("sl","tp1","tp2","tp3"):
        if key in upd and upd[key] is not None and upd[key] != trade.get(key):
            old, new = trade.get(key), upd[key]
            await _tg_send(_compose_change_msg(trade, key.upper() + " moved", f"`{old}` → `{new}`"))
            events.append(f"moved_{key}:{old}->{new}")
            trade[key] = new

    # הגעה ליעדים
    for tgt in ("tp1","tp2","tp3","sl"):
        flag = f"{tgt}_hit"
        if _bool(upd.get(flag, False)) and not trade["hits"].get(tgt):
            trade["hits"][tgt] = True
            await _tg_send(_compose_hit_msg(trade, tgt.upper(), trade.get(tgt)))
            events.append(f"hit_{tgt}")

    # סטטוס
    if upd.get("status") in ("pending","open","closed") and upd["status"] != trade.get("status"):
        events.append(f"status:{trade.get('status')}->{upd['status']}")
        trade["status"] = upd["status"]

    # ציונים וניהול
    for k in ("final_score","management_summary","improvement_suggestion"):
        if k in upd and upd[k] is not None:
            trade[k] = upd[k]

    # דוח סופי / PnL
    for k in ("pnl_usd","pnl_pct","tp1_usd","tp2_usd","tp3_usd","sl_usd","closed_ts","expiry_ts"):
        if k in upd:
            trade[k] = upd[k]

    # היסטוריה
    if events:
        trade["history"].append({"ts": int(time.time()), "events": events})

    await _store_trade(trade)

    # אם נסגר — שלח דוח סופי קצר
    if trade.get("status") == "closed":
        await _tg_send(_compose_final_report(trade))

    return {"ok": True, "trade": trade}

































