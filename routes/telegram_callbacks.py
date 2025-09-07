# routes/telegram_callbacks.py
from __future__ import annotations
import os, json, re, logging
from typing import Any, Dict, Optional, Tuple

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from telegram import Update

from utils.telegram_notifier import handle_callback_action
from utils.binance_client import place_tp_ladder, set_breakeven_stop

logger = logging.getLogger("algogpt.tg_callbacks")

router = APIRouter(prefix="/telegram/callbacks", tags=["TelegramCallbacks"])

# ===== Helpers (לוקליים, ללא ENV חובה) =====
_APPROVE_HINTS = ("approve", "approved", "✅", "אשר", "אושר", "מאושר", "לאשר")
_SIDE_HINTS = {
    "long": "LONG", "buy": "LONG", "לונג": "LONG", "קנייה": "LONG",
    "short": "SHORT", "sell": "SHORT", "שורט": "SHORT", "מכירה": "SHORT"
}

def _detect_approved(update: Update, result: Any) -> bool:
    """מזהה אישור מתוך ה-callback או תוצאת ההנדלר הקיים שלך."""
    # 1) פרשנות תוצאת ההנדלר אם היא מילונית
    if isinstance(result, dict):
        if result.get("approved") is True or str(result.get("action","")).lower() in ("approve","approved"):
            return True
    # 2) אותות מה-callback data
    try:
        data = update.callback_query.data if update.callback_query else None
        if data:
            # JSON? אם כן, ננסה לקרוא שדה action
            try:
                dj = json.loads(data)
                act = str(dj.get("action","")).lower()
                if act in ("approve","approved"):
                    return True
            except Exception:
                # מחרוזת רגילה
                s = str(data).lower()
                if any(h in s for h in _APPROVE_HINTS):
                    return True
    except Exception:
        pass
    # 3) טקסט ההודעה
    text = update.callback_query.message.text if (update and update.callback_query and update.callback_query.message) else ""
    if text and any(h in text.lower() for h in _APPROVE_HINTS):
        return True
    return False

def _extract_symbol_side(update: Update, result: Any) -> Tuple[Optional[str], Optional[str]]:
    """
    מנסה לשלוף symbol/side מהתוצאה/טקסט. לא תלוי ב-ENV.
    פורמטים שכיחים: "BTCUSDT LONG", "ETHUSDT – Short", "Symbol: SOLUSDT, Side: BUY/SELL".
    """
    # עדיפות לשדות מפורשים בתוצאת ההנדלר
    if isinstance(result, dict):
        sym = result.get("symbol") or result.get("sym") or result.get("ticker")
        side = result.get("side")
        if isinstance(sym, str) and sym.strip():
            if isinstance(side, str) and side.strip():
                sd = side.strip().upper()
                if sd in ("LONG","SHORT"):
                    return sym.strip().upper(), sd
                # BUY/SELL → המר ל-LONG/SHORT
                if sd in ("BUY","SELL"):
                    return sym.strip().upper(), ("LONG" if sd=="BUY" else "SHORT")

    # parse מתוך הטקסט
    text = update.callback_query.message.text if (update and update.callback_query and update.callback_query.message) else ""
    if text:
        # חפש סימבול crypto טיפוסי (אותיות+USDT)
        m = re.search(r"\b([A-Z]{3,15}USDT)\b", text)
        sym = m.group(1) if m else None
        # חפש צד
        low = text.lower()
        side = None
        for k, v in _SIDE_HINTS.items():
            if k in low:
                side = v; break
        if sym and side:
            return sym, side

    # נסה מה-data
    try:
        data = update.callback_query.data if update.callback_query else None
        if data:
            try:
                dj = json.loads(data)
                sym = (dj.get("symbol") or dj.get("sym") or dj.get("ticker") or "").strip().upper()
                sd  = (dj.get("side") or dj.get("position") or dj.get("dir") or "").strip().upper()
                if sym and sd:
                    if sd in ("LONG","SHORT"):
                        return sym, sd
                    if sd in ("BUY","SELL"):
                        return sym, ("LONG" if sd=="BUY" else "SHORT")
            except Exception:
                pass
    except Exception:
        pass
    return None, None

def _be_immediate_allowed() -> bool:
    """
    ברירת מחדל: BE רק אחרי TP1 (בלי לגעת ENV). אם ENV הגדיר אחרת—נכבד.
    """
    return str(os.getenv("TP_BE_ONLY_AFTER_TP1","1")).lower() in ("0","false","no")

def _be_offset_bps_default() -> float:
    try:
        return float(os.getenv("TP_BE_OFFSET_BPS","5"))
    except Exception:
        return 5.0

# ===== Webhook יחיד =====
@router.post("/")
async def telegram_callback_webhook(request: Request):
    try:
        body = await request.body()
        update = Update.de_json(json.loads(body), None)

        # הרץ את ההנדלר הקיים שלך (שומר תאימות)
        result = await handle_callback_action(update)

        # אם מדובר באישור → הקם סולם TP אוטומטי (עם ברירות מחדל בתוך binance_client)
        approved = _detect_approved(update, result)
        ladder = None
        be_res = None

        if approved:
            symbol, side = _extract_symbol_side(update, result)
            if symbol and side:
                try:
                    ladder = place_tp_ladder(symbol)  # אחוזים/ספליטים ברירת־מחדל בתוך המודול
                except Exception as e:
                    logger.warning("TP ladder failed: %s", e)
                    ladder = {"ok": False, "error": str(e)}

                # BE מיידי? כברירת־מחדל לא. אם ENV מתיר—נגדיר כאן.
                if _be_immediate_allowed():
                    try:
                        be_res = set_breakeven_stop(symbol, offset_bps=_be_offset_bps_default())
                    except Exception as e:
                        logger.warning("BE set failed: %s", e)
                        be_res = {"ok": False, "error": str(e)}

        return JSONResponse(content={"ok": True, "result": result, "ladder": ladder, "be": be_res})
    except Exception as e:
        logger.exception("telegram_callback_webhook failed")
        return JSONResponse(status_code=500, content={"ok": False, "error": str(e)})



