# routes/alerts.py
from __future__ import annotations
import os, hmac, hashlib, time, json, logging
from typing import Any, Dict, Optional, Tuple
from contextlib import suppress

from fastapi import APIRouter, Body, Header, Request, HTTPException
from pydantic import BaseModel
from utils.telegram_notifier import make_callback

logger = logging.getLogger("algogpt.alerts")
router = APIRouter(tags=["alerts"])

# ===== Auth (רך) =====
API_TOKEN = (os.getenv("API_TOKEN") or os.getenv("PRIMARY_API_TOKEN") or "").strip()

def _api_key_ok(hdr: Optional[str]) -> bool:
    if not API_TOKEN:
        return True
    return bool(hdr and hdr.strip() == API_TOKEN)

# ===== Optional HMAC (ingest) =====
INGEST_SEC = (os.getenv("ALERTS_INGEST_HMAC_SECRET") or "").strip()
INGEST_HEX = (os.getenv("ALERTS_INGEST_HMAC_KEY_IS_HEX", "0").lower() in ("1","true","yes","on"))
DEBUG_HMAC  = (os.getenv("DEBUG_ALERTS_HMAC_CHECK","0").lower() in ("1","true","yes","on"))

def _hmac_check(route: str, body_bytes: bytes, ts: Optional[str], nonce: Optional[str], sig: Optional[str]) -> Tuple[bool,str]:
    if not INGEST_SEC:
        return True, "no_secret"
    if not (ts and nonce and sig):
        return False, "missing_headers"
    msg = f"{route}|{ts}|{nonce}|".encode("utf-8") + (body_bytes or b"")
    key = bytes.fromhex(INGEST_SEC) if INGEST_HEX and len(INGEST_SEC) % 2 == 0 else INGEST_SEC.encode("utf-8")
    calc = hmac.new(key, msg, hashlib.sha256).hexdigest()
    return (calc == sig, "bad_sig" if calc != sig else "ok")

# ===== Optional ConfirmStore =====
_HAS_CONFIRM = False
with suppress(Exception):
    # נסה קודם מ-main (אם הוגדר שם)
    from main import ConfirmStore as _ConfirmStoreMain  # type: ignore
    ConfirmStore = _ConfirmStoreMain  # type: ignore
    _HAS_CONFIRM = True
if not _HAS_CONFIRM:
    # Fallback קטן בזיכרון — לא חובה.
    class ConfirmStore:  # type: ignore
        _items: Dict[str, Dict[str, Any]] = {}
        @classmethod
        def create(cls, req: Dict[str, Any]) -> None:
            cls._items[str(req.get("ticket_id","TKT"))] = {"req": dict(req), "ts": time.time()}
    _HAS_CONFIRM = True

# ===== Auto-execution notification (ללא כפתורים) =====
async def _tg_send_auto_notification(plan: Dict[str, Any], result: Dict[str, Any]) -> None:
    """שולח התראה על ביצוע אוטומטי - ללא כפתורי אישור"""
    with suppress(Exception):
        from utils.alerts import send_telegram_message  # type: ignore
        from utils.trade_reports import get_israel_time_str  # type: ignore
        
        sym = plan.get("symbol", "")
        side = plan.get("side", "")
        lev = plan.get("leverage", "")
        qty = plan.get("qty", "")
        
        # חלץ TP/SL מהנתונים
        tp_list = plan.get("tp", [])
        sl_dict = plan.get("sl", {})
        
        # בנה הודעה עשירה
        emoji_side = "🟢" if side == "BUY" else "🔴"
        israel_time = get_israel_time_str()
        
        lines = [
            f"🤖 <b>FULL AUTO - EXECUTED</b>",
            f"🕐 <b>שעון ישראל:</b> {israel_time}",
            f"",
            f"{emoji_side} <b>{sym}</b>",
            f"📊 Direction: <b>{side}</b> (Leverage: x{lev})",
            f"💰 Quantity: <code>{qty:.6f}</code>",
        ]
        
        if plan.get("budget_usd"):
            lines.append(f"💵 Budget: <code>${plan['budget_usd']:.2f}</code>")
        
        # הוסף Entry/SL/TP
        entry = plan.get("entry")
        if entry:
            lines.append(f"🎯 Entry: <code>{entry:.2f}</code>")
        
        if sl_dict and sl_dict.get("stopPrice"):
            lines.append(f"🛑 Stop Loss: <code>{sl_dict['stopPrice']:.2f}</code>")
        
        if tp_list:
            lines.append(f"🎯 Take Profit:")
            for i, tp in enumerate(tp_list[:3], 1):
                if isinstance(tp, dict) and tp.get("price"):
                    lines.append(f"   TP{i}: <code>{tp['price']:.2f}</code>")
        
        # Quality Score
        if plan.get("score"):
            lines.append(f"⭐ Quality Score: <code>{plan['score']:.1f}/10</code>")
        
        # תוצאת הביצוע
        if result.get("ok"):
            lines.append(f"")
            lines.append(f"✅ <b>Status: LIVE POSITION OPENED</b>")
            if result.get("order_id"):
                lines.append(f"🆔 Order ID: <code>{result['order_id']}</code>")
        else:
            lines.append(f"")
            lines.append(f"❌ <b>Status: EXECUTION FAILED</b>")
            if result.get("error"):
                lines.append(f"⚠️ Error: {result['error']}")
        
        lines.append(f"")
        lines.append(f"<i>🤖 Auto-executed without approval</i>")
        
        await send_telegram_message(
            "\n".join(lines), 
            parse_mode="HTML", 
            disable_preview=True
        )

# ===== Telegram send helper (משופר עם כפתורים ופרטים מלאים) =====
async def _tg_send_plan(plan: Dict[str, Any]) -> None:
    with suppress(Exception):
        from utils.alerts import send_telegram_message  # type: ignore
        from utils.trade_reports import get_israel_time_str, is_trade_expired  # type: ignore
        
        sym = plan.get("symbol", "")
        side = plan.get("side", "")
        lev = plan.get("leverage", "")
        qty = plan.get("qty", "")
        ticket_id = plan.get("ticket_id", "")
        created_at = plan.get("created_at", "")
        
        # חלץ TP/SL מהנתונים
        tp_list = plan.get("tp", [])
        sl_dict = plan.get("sl", {})
        
        # בדוק אם זה GRID proposal
        is_grid = plan.get("is_grid", False)
        
        # בנה הודעה עשירה בפרטים
        emoji_side = "🟢" if side == "BUY" else "🔴"
        
        # בדוק אם ההצעה פגה תוקף
        expired = is_trade_expired(created_at, max_age_hours=2)
        expired_tag = "⚠️ <b>פג תוקף</b> | " if expired else ""
        
        # קבל timestamp ישראלי
        israel_time = get_israel_time_str()
        
        # GRID או Regular proposal
        if is_grid:
            grid_min = plan.get("grid_min", 0)
            grid_max = plan.get("grid_max", 0)
            grid_levels = plan.get("grid_levels", 0)
            
            lines = [
                f"🔷 <b>NEW GRID TRADE PROPOSAL</b>",
                f"🕐 <b>שעון ישראל:</b> {israel_time}",
                f"{expired_tag}",
                f"💎 <b>{sym}</b>",
                f"📊 Direction: <b>{side}</b>",
                f"📈 Grid Range: <code>{grid_min:.2f} - {grid_max:.2f}</code>",
                f"🎯 Levels: <code>{grid_levels}</code>",
            ]
        else:
            lines = [
                f"{emoji_side} <b>NEW TRADE PROPOSAL</b>",
                f"🕐 <b>שעון ישראל:</b> {israel_time}",
                f"{expired_tag}",
                f"💎 <b>{sym}</b>",
                f"📊 Direction: <b>{side}</b> (Leverage: x{lev})",
                f"💰 Quantity: <code>{qty:.6f}</code>",
            ]
        
        if plan.get("budget_usd"):
            lines.append(f"💵 Budget: <code>${plan['budget_usd']:.2f}</code>")
        
        # הוסף Entry/SL/TP אם קיימים
        entry = plan.get("entry")
        if entry:
            lines.append(f"🎯 Entry: <code>{entry:.2f}</code>")
        
        if sl_dict and sl_dict.get("stopPrice"):
            lines.append(f"🛑 Stop Loss: <code>{sl_dict['stopPrice']:.2f}</code>")
        
        if tp_list:
            lines.append(f"🎯 Take Profit:")
            for i, tp in enumerate(tp_list[:3], 1):
                if isinstance(tp, dict) and tp.get("price"):
                    lines.append(f"   TP{i}: <code>{tp['price']:.2f}</code>")
        
        # חישובי RR ו-Success
        if plan.get("score"):
            lines.append(f"⭐ Quality Score: <code>{plan['score']:.1f}/10</code>")
        
        # Success % אם קיים
        success_pct = plan.get("success_pct")
        if success_pct:
            lines.append(f"📈 Success Probability: <code>{success_pct:.1f}%</code>")
        
        # סיבה/אסטרטגיה
        if plan.get("why"):
            lines.append(f"")
            lines.append(f"📝 Strategy: {plan['why'][:150]}")
        
        lines.append(f"")
        lines.append(f"⏱️ Timeframe: <code>{plan.get('timeframe', '15m')}</code>")
        lines.append(f"")
        lines.append(f"<i>🤖 Auto-analyzed by AI Scanner</i>")
        
        # כפתורים ירוקים/אדומים (פורמט: CONFIRM:ACTION:TICKET_ID עם חתימה HMAC)
        keyboard = {
            "inline_keyboard": [
                [
                    {"text": "✅ APPROVE", "callback_data": make_callback("APPROVE", ticket_id)},
                    {"text": "❌ REJECT", "callback_data": make_callback("REJECT", ticket_id)}
                ],
                [
                    {"text": "📊 View Full Details", "callback_data": f"CONFIRM:DETAILS:{ticket_id}"}
                ]
            ]
        }
        
        await send_telegram_message(
            "\n".join(lines), 
            parse_mode="HTML", 
            disable_preview=True,
            reply_markup=keyboard
        )

# ===== Binance helpers (רק למחיר) =====
def _get_client_soft():
    try:
        from binance.client import Client  # type: ignore
    except Exception as e:
        return None, f"binance_import_failed: {e}"
    ak = os.getenv("BINANCE_API_KEY","").strip()
    sk = os.getenv("BINANCE_API_SECRET","").strip()
    if not ak or not sk:
        return None, "binance_keys_missing"
    try:
        return Client(ak, sk), None
    except Exception as e:
        return None, f"binance_client_init_failed: {e}"

def _last_price(client, symbol: str) -> float:
    p = client.futures_symbol_ticker(symbol=symbol.upper())
    return float(p["price"])

# ===== Request/Response models =====
class IngestReq(BaseModel):
    # חובה:
    symbol: str
    side: str  # BUY | SELL | LONG | SHORT
    market: str = "futures"
    # אחת מהאפשרויות: qty או budget_usd (+ leverage)
    qty: Optional[float] = None
    budget_usd: Optional[float] = None
    leverage: Optional[int] = None
    # מידע נוסף (לא חובה)
    ticket_id: Optional[str] = None
    timeframe: Optional[str] = "15m"
    score: Optional[float] = 0.0
    reason: Optional[str] = ""
    require_approval: Optional[bool] = None
    tp1: Optional[dict] | Optional[float] = None
    tp2: Optional[dict] | Optional[float] = None
    tp3: Optional[dict] | Optional[float] = None
    sl: Optional[dict] | Optional[float] = None
    entry: Optional[float] = None
    success_pct: Optional[float] = None
    current_price: Optional[float] = None
    note: Optional[str] = None
    # GRID parameters (optional)
    is_grid: Optional[bool] = False
    grid_min: Optional[float] = None
    grid_max: Optional[float] = None
    grid_levels: Optional[int] = None
    grid_side: Optional[str] = None
    grid_step_pct: Optional[float] = None
    grid_take_profit_pct: Optional[float] = None
    trade_type: Optional[str] = None
    # Extra fields (optional)
    trade_id: Optional[str] = None
    notional_usd: Optional[float] = None
    chat_id: Optional[str] = None

def _ticket_id_for(req: IngestReq) -> str:
    base = {
        "symbol": req.symbol.upper(),
        "side": req.side.upper(),
        "market": (req.market or "futures").lower(),
        "timeframe": req.timeframe,
        "reason": req.reason or "",
        "score": float(req.score or 0),
    }
    h = hashlib.sha256(json.dumps(base, sort_keys=True).encode()).hexdigest()[:16]
    return f"TKT-{h}"

def _compute_qty_from_budget(symbol: str, budget_usd: float, leverage: int) -> tuple[float, Optional[str]]:
    cli, err = _get_client_soft()
    if not cli:
        return 0.0, err or "binance_client_error"
    try:
        px = _last_price(cli, symbol)
        if px <= 0:
            return 0.0, "bad_price"
        qty = (float(budget_usd) * float(leverage)) / px
        return float(qty), None
    except Exception as e:
        return 0.0, f"price_fetch_failed: {e}"

def _to_float(x):
    try:
        return float(x) if x is not None else None
    except:
        return None

# ===== Endpoints =====
@router.post("/alerts/ingest")
async def alerts_ingest(
    req: IngestReq = Body(...),
    request: Request = None,
    x_api_key: Optional[str] = Header(None, alias="x-api-key"),
    x_timestamp: Optional[str] = Header(None, alias="X-Timestamp"),
    x_nonce: Optional[str] = Header(None, alias="X-Nonce"),
    x_signature: Optional[str] = Header(None, alias="X-Signature"),
):
    try:
        # API key (רך): אם הוגדר, נדרוש אותו
        if not _api_key_ok(x_api_key):
            return {"ok": False, "error": "unauthorized"}
    except Exception as e:
        logger.error(f"alerts_ingest ERROR: {e}", exc_info=True)
        return {"ok": False, "error": str(e)}

    # HMAC אופציונלי (לפי גוף המקורי)
    raw_body = b""
    with suppress(Exception):
        raw_body = await request.body() if request else json.dumps(req.dict()).encode("utf-8")
    if DEBUG_HMAC and INGEST_SEC:
        ok, why = _hmac_check("/alerts/ingest", raw_body, x_timestamp, x_nonce, x_signature)
        if not ok:
            return {"ok": False, "error": f"hmac_{why}"}

    sym = (req.symbol or "").upper().strip()
    side_raw = (req.side or "").upper().strip()
    # תמיכה ב-LONG/SHORT (Futures) וגם ב-BUY/SELL (קלאסי)
    if side_raw in ("LONG", "BUY"):
        side = "BUY"
    elif side_raw in ("SHORT", "SELL"):
        side = "SELL"
    else:
        return {"ok": False, "error": "bad_symbol_or_side"}
    
    if sym == "":
        return {"ok": False, "error": "bad_symbol"}

    # GRID proposals לא צריכים qty
    qty = req.qty
    if qty is None and not req.is_grid:
        bud = float(req.budget_usd or 0.0)
        lev = int(req.leverage or int(os.getenv("DEFAULT_LEVERAGE","5")))
        if bud <= 0:
            return {"ok": False, "error": "qty_or_budget_required"}
        qty, qerr = _compute_qty_from_budget(sym, bud, lev)
        if qerr:
            return {"ok": False, "error": qerr}
        req.qty = qty
        req.leverage = lev
    elif req.is_grid:
        # GRID proposals: qty לא רלוונטי
        req.qty = 0.0
        req.leverage = 1  # GRID לא ממונף

    # המר TP/SL מ-float ל-dict אם צריך (תמיכה ב-Worker format)
    def _to_tp_dict(val, idx):
        if isinstance(val, dict):
            return val
        elif isinstance(val, (int, float)) and float(val) > 0:
            return {"price": float(val), "pct": 25.0 if idx == 1 else (33.0 if idx == 2 else 100.0)}
        return None
    
    tp_dicts = [_to_tp_dict(x, i) for i, x in enumerate([req.tp1, req.tp2, req.tp3], 1)]
    tp_list = [x for x in tp_dicts if x is not None]
    
    sl_data = req.sl
    if isinstance(sl_data, (int, float)) and float(sl_data) > 0:
        sl_dict = {"stopPrice": float(sl_data)}
    elif isinstance(sl_data, dict):
        sl_dict = sl_data
    else:
        sl_dict = {}
    
    # Smart portfolio management
    score = float(req.score or 0)
    base_lev = int(req.leverage or int(os.getenv("DEFAULT_LEVERAGE","5")))
    
    # Apply score-based leverage and budget allocation
    try:
        from utils.portfolio_manager import calculate_score_based_leverage, calculate_trade_budget
        
        smart_lev = calculate_score_based_leverage(base_lev, score, max_lev=20)
        budget_result = calculate_trade_budget(score)
        
        if budget_result.get("ok") and not req.budget_usd:
            smart_budget = budget_result["budget_usdt"]
        else:
            smart_budget = float(req.budget_usd or 0)
    except Exception:
        smart_lev = base_lev
        smart_budget = float(req.budget_usd or 0)
    
    # קרא את מצב האישור מהמסד נתונים (או ENV כברירת מחדל)
    require_approval_default = True
    try:
        import psycopg2
        DATABASE_URL = os.getenv("DATABASE_URL")
        if DATABASE_URL:
            conn = psycopg2.connect(DATABASE_URL)
            with conn.cursor() as cur:
                cur.execute("SELECT value FROM system_settings WHERE key = 'approval_mode'")
                row = cur.fetchone()
                if row:
                    require_approval_default = str(row[0]).lower() in ("true", "1", "yes", "on")
                    logger.info(f"[APPROVAL MODE] DB value: {row[0]}, require_approval_default={require_approval_default}")
            conn.close()
        else:
            raise Exception("DATABASE_URL not set")
    except Exception as e:
        # אם אין מסד נתונים או שגיאה - קרא מ-ENV
        require_approval_default = os.getenv("APPROVAL_ENABLED", "0").lower() in ("1", "true", "yes", "on")
        logger.info(f"[APPROVAL MODE] DB read failed ({e}), using ENV: require_approval_default={require_approval_default}")
    
    final_require_approval = bool(req.require_approval if req.require_approval is not None else require_approval_default)
    logger.info(f"[APPROVAL MODE] {sym} {side}: req.require_approval={req.require_approval}, require_approval_default={require_approval_default}, final={final_require_approval}")
    
    plan: Dict[str, Any] = {
        "symbol": sym,
        "side": side,
        "market": (req.market or "futures").lower(),
        "timeframe": req.timeframe,
        "leverage": smart_lev,  # Score-based leverage
        "qty": float(req.qty or 0),
        "score": score,
        "why": req.reason or "",
        "tp": tp_list,
        "sl": sl_dict,
        # GRID parameters (if present)
        "is_grid": req.is_grid,
        "grid_min": req.grid_min,
        "grid_max": req.grid_max,
        "grid_levels": req.grid_levels,
        "grid_side": req.grid_side,
        "grid_step_pct": req.grid_step_pct,
        "grid_take_profit_pct": req.grid_take_profit_pct,
        "budget_usd": smart_budget,  # Smart budget allocation
        "order_type": "MARKET",
        "require_approval": final_require_approval,
        "entry": _to_float(req.entry),
        "success_pct": _to_float(req.success_pct) if req.success_pct else score,
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }

    tid = req.ticket_id or _ticket_id_for(req)
    plan["ticket_id"] = tid

    if _HAS_CONFIRM:
        with suppress(Exception):
            ConfirmStore.create({  # type: ignore
                "ticket_id": tid, "source": "ingest",
                "symbol": sym, "market": plan["market"], "timeframe": req.timeframe,
                "side": side, "score": float(req.score or 0), "reason": req.reason or "",
                "require_approval": bool(plan["require_approval"]), "ts": int(time.time()),
            })

    # 🔍 CRITICAL LOGGING: Debug approval mode decision
    print(f"\n\n🔍 [APPROVAL DEBUG] {sym} {side}:")
    print(f"   - req.require_approval: {req.require_approval}")
    print(f"   - require_approval_default: {require_approval_default}")
    print(f"   - final_require_approval: {final_require_approval}")
    print(f"   - plan['require_approval']: {plan['require_approval']}")
    print(f"   - Decision: {'FULL AUTO' if not plan['require_approval'] else 'APPROVAL MODE'}\n\n")
    logger.info(f"🔍 [APPROVAL DEBUG] {sym} {side}:")
    logger.info(f"   - req.require_approval: {req.require_approval}")
    logger.info(f"   - require_approval_default: {require_approval_default}")
    logger.info(f"   - final_require_approval: {final_require_approval}")
    logger.info(f"   - plan['require_approval']: {plan['require_approval']}")
    logger.info(f"   - Decision: {'FULL AUTO' if not plan['require_approval'] else 'APPROVAL MODE'}")
    
    # אם במצב FULL AUTO - בצע מיידית
    print(f"🔍 [PRE-IF] Checking condition: plan['require_approval']={plan['require_approval']}, type={type(plan['require_approval'])}")
    print(f"🔍 [PRE-IF] Condition result: not plan['require_approval'] = {not plan['require_approval']}")
    if not plan["require_approval"]:
        print(f"🚀 [INSIDE IF] YES! Entering FULL AUTO execution block!")
        print(f"🚀 [FULL AUTO] Starting execution for {sym} {side} (no approval required)")
        try:
            print(f"📦 [FULL AUTO] About to import auto_execute_plan...")
            from utils.auto_executor import auto_execute_plan
            print(f"📦 [FULL AUTO] Imported auto_execute_plan successfully")
            print(f"📋 [FULL AUTO] Plan details: {json.dumps(plan, indent=2)}")
            
            print(f"🚀 [FULL AUTO] About to call auto_execute_plan...")
            result = await auto_execute_plan(plan)
            print(f"✅ [FULL AUTO] auto_execute_plan returned: {result}")
            logger.info(f"✅ [FULL AUTO] Execution completed: {result}")
            
            # שלח התראה לטלגרם (ללא כפתורים)
            try:
                await _tg_send_auto_notification(plan, result)
                logger.info(f"📱 [FULL AUTO] Telegram notification sent")
            except Exception as notif_err:
                logger.warning(f"⚠️ [FULL AUTO] Failed to send auto-execution notification: {notif_err}")
            
            return {
                "ok": True, 
                "ticket_id": tid, 
                "symbol": sym, 
                "qty": float(req.qty or 0), 
                "leverage": int(plan["leverage"]),
                "auto_executed": True,
                "execution_result": result
            }
        except Exception as exec_err:
            logger.error(f"❌ [FULL AUTO] Execution failed for {sym}: {exec_err}", exc_info=True)
            # אם הביצוע נכשל - נשלח לאישור במקום
            plan["require_approval"] = True
            logger.info(f"🔄 [FULL AUTO] Falling back to approval mode due to execution error")
    else:
        logger.info(f"⏸️ [APPROVAL MODE] Skipping auto-execution for {sym} {side} - sending to Telegram for approval")
    
    # מצב APPROVAL - שלח לטלגרם עם כפתורים
    try:
        logger.info(f"📱 [APPROVAL MODE] Sending plan to Telegram with approval buttons")
        await _tg_send_plan(plan)  # רך: אם נכשל לא מפיל
        logger.info(f"✅ [APPROVAL MODE] Telegram message sent successfully")
    except Exception as e:
        logger.error(f"❌ [APPROVAL MODE] _tg_send_plan ERROR: {e}", exc_info=True)

    return {"ok": True, "ticket_id": tid, "symbol": sym, "qty": float(req.qty or 0), "leverage": int(plan["leverage"])}

@router.get("/alerts/ingest")
async def alerts_ingest_health():
    return {"ok": True, "ingest": "ready"}





























