# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import re
import time
import logging
import asyncio
from contextlib import suppress
from typing import List, Optional, Dict, Any, Tuple, Callable

# פעולות טלאי/BE מתבצעות דרך binance_client (חייב להיות קיים אצלך)
from utils.binance_client import place_tp_ladder, set_breakeven_stop

logger = logging.getLogger("algogpt.tp_helper")

# ──────────────────────────────────────────────────────────────────────────────
# ENV flags
# ──────────────────────────────────────────────────────────────────────────────
LADDER_TP_ENABLE = os.getenv("LADDER_TP_ENABLE", "1") == "1"
TP_LADDER_ON_APPROVE = os.getenv("TP_LADDER_ON_APPROVE", "1") == "1"

STREAM_TP_BE = os.getenv("STREAM_TP_BE", "true").lower() in ("1", "true", "yes")
TP_BE_OFFSET_BPS = float(os.getenv("TP_BE_OFFSET_BPS", "5"))  # 0.05%
TP_BE_ONLY_AFTER_TP1 = os.getenv("TP_BE_ONLY_AFTER_TP1", "1") == "1"

# Defaults for ladder (binance_client כבר מכיר)
ENV_TP_PCTS = os.getenv("LADDER_TP_DEFAULT_PCTS", "1.8,3.2,5.5")
ENV_TP_SPLITS = os.getenv("LADDER_TP_DEFAULT_SPLITS", "0.4,0.35,0.25")

# Profit-Lock bands (RR levels) – אופציונלי
PROFIT_LOCK_STEPS = os.getenv("PROFIT_LOCK_STEPS", "1.0,1.5,2.0")

# Idempotency: הימנעות מחזרת סולם בתדירות גבוהה
_last_ladder_at: Dict[str, float] = {}
_LADDER_COOLDOWN_SEC = 60.0


def _now() -> float:
    return time.time()


def _parse_tp_pcts_from_text(text: str) -> List[float]:
    """
    מחפש תבניות כמו: TP1=+1.8% | TP2=+3.2% | TP3=+5.5%
    ומחזיר רשימת אחוזים בסדר עולה.
    """
    if not text:
        return []
    pcts: List[float] = []

    # חפש "TPn=+x.x%"
    for m in re.finditer(r"TP\d+\s*=\s*\+?(-?\d+(?:\.\d+)?)\s*%", text, re.IGNORECASE):
        with suppress(Exception):
            pcts.append(float(m.group(1)))

    # אם לא מצא — חפש אחוזים בסמיכות ל־TP או אחרי סימן אחוז כללי
    if not pcts:
        for m in re.finditer(r"(?:TP\d*[^0-9\-+]{0,8})?(\+?-?\d+(?:\.\d+)?)\s*%", text, re.IGNORECASE):
            with suppress(Exception):
                val = float(m.group(1))
                if val > 0:
                    pcts.append(val)

    pcts = [x for x in pcts if x > 0]
    pcts.sort()
    return pcts


def _env_list_of_floats(csv_str: str) -> List[float]:
    out: List[float] = []
    for part in (csv_str or "").split(","):
        part = part.strip()
        if not part:
            continue
        with suppress(Exception):
            out.append(float(part))
    return out


def _deduce_tp_inputs(
    decision: Dict[str, Any],
    tp_pcts: Optional[List[float]],
    splits: Optional[List[float]],
) -> Tuple[List[float], List[float]]:
    """
    גוזר אחוזי TP וחלוקות מהעדפות/טקסט/ENV.
    סדר עדיפויות:
      1) פרמטרים ישירים (tp_pcts/splits ב־decision)
      2) ניתוח מתוך ה־note/description
      3) ברירות מחדל מה־ENV
    """
    # 1) פרמטרים ישירים
    if tp_pcts and len(tp_pcts) > 0:
        pcts = [float(x) for x in tp_pcts if float(x) > 0]
    else:
        # 2) נסה לחלץ מהטקסט
        text = str(decision.get("note") or decision.get("description") or "")
        parsed = _parse_tp_pcts_from_text(text)
        pcts = parsed if parsed else _env_list_of_floats(ENV_TP_PCTS)

    if splits and len(splits) == len(pcts):
        s = [float(x) for x in splits]
    else:
        s = _env_list_of_floats(ENV_TP_SPLITS)
        if len(s) != len(pcts):
            # אם לא תואם — חלק שווה בשווה
            s = [round(1.0 / len(pcts), 6)] * len(pcts) if pcts else []

    # נרמול סכום חלוקות ל־1.0
    tot = sum(s) if s else 0.0
    if s and abs(tot - 1.0) > 1e-3:
        s = [x / tot for x in s]

    return pcts, s


async def _maybe_set_be(symbol: str, side: str, decision: Dict[str, Any]) -> Dict[str, Any]:
    """
    הצבת Stop BE בהתאם לדגלי ENV.
    """
    if not STREAM_TP_BE:
        return {"ok": True, "skipped": True, "reason": "be_stream_disabled"}
    try:
        kw = dict(
            symbol=symbol,
            side=side,
            offset_bps=float(decision.get("be_offset_bps", TP_BE_OFFSET_BPS)),
            only_after_tp1=bool(decision.get("be_only_after_tp1", TP_BE_ONLY_AFTER_TP1)),
        )
        # נסה כמה תבניות חתימה כדי להיות סלחני לשינויים פנימיים:
        # 1) kwargs נקיים
        try:
            res = await _maybe_await(set_breakeven_stop(**kw))
            return {"ok": True, "result": res}
        except TypeError:
            # 2) עטיפה עם decision
            res = await _maybe_await(set_breakeven_stop(**kw, decision=decision))
            return {"ok": True, "result": res}
    except Exception as e:
        logger.warning("tp_helper.set_be.failed: %s", e)
        return {"ok": False, "error": f"{e}"}


async def _maybe_await(x):
    if asyncio.iscoroutine(x):
        return await x
    return x


async def _call_place_tp_ladder(symbol: str, side: str, pcts: List[float], splits: List[float], decision: Dict[str, Any]) -> Dict[str, Any]:
    """
    קריאה סלחנית ל־place_tp_ladder עם ניסיונות חתימה שונים כדי להבטיח תאימות.
    """
    # ניסיון 1: החתימה ה"נקייה"
    try:
        res = await _maybe_await(place_tp_ladder(symbol=symbol, side=side, pcts=pcts, splits=splits))
        return {"ok": True, "result": res, "pattern": "kwargs-minimal"}
    except TypeError:
        pass
    # ניסיון 2: הוספת decision
    try:
        res = await _maybe_await(place_tp_ladder(symbol=symbol, side=side, pcts=pcts, splits=splits, decision=decision))
        return {"ok": True, "result": res, "pattern": "kwargs+decision"}
    except TypeError:
        pass
    # ניסיון 3: אם יש כמות/צד פוזיציה — ננסה להעביר
    try:
        qty = float(decision.get("qty") or decision.get("quantity") or 0.0)
        position_side = (decision.get("position_side") or decision.get("positionSide") or "").upper() or None
        res = await _maybe_await(place_tp_ladder(symbol=symbol, side=side, pcts=pcts, splits=splits, qty=qty or None, position_side=position_side))
        return {"ok": True, "result": res, "pattern": "kwargs+qty+posSide"}
    except Exception as e:
        return {"ok": False, "error": f"{e}"}


async def apply_tp_ladder_and_be(decision: Dict[str, Any], *, force: bool = False) -> Dict[str, Any]:
    """
    פונקציית העזר הראשית: מציבה סולם TP (אם מופעל) ו־BE Stop בהתאם לפוליסי.
    פרמטרי כניסה מינימליים ב־decision:
      - symbol: str
      - side: "BUY"/"SELL"
      - note/description: אופציונלי לצורך חילוץ אחוזים
      - tp_pcts / tp_splits: אופציונלי – עקיפה ידנית
    """
    symbol = str(decision.get("symbol") or "").upper()
    side = str(decision.get("side") or "").upper()
    if not (symbol and side in ("BUY", "SELL")):
        return {"ok": False, "error": "bad_decision_params"}

    # קירור/אידמפוטנטיות על סולם
    now = _now()
    last = _last_ladder_at.get(symbol)
    if not force and last and (now - last) < _LADDER_COOLDOWN_SEC:
        cool_left = round(_LADDER_COOLDOWN_SEC - (now - last), 1)
        logger.info("tp_helper: cooldown active for %s (%.1fs left)", symbol, cool_left)
        ladder_part = {"ok": True, "skipped": True, "reason": f"cooldown_{cool_left}s"}
    else:
        ladder_part = {"ok": True, "skipped": True, "reason": "disabled"}
        if LADDER_TP_ENABLE and TP_LADDER_ON_APPROVE:
            pcts, splits = _deduce_tp_inputs(decision, decision.get("tp_pcts"), decision.get("tp_splits"))
            if not pcts:
                ladder_part = {"ok": True, "skipped": True, "reason": "no_pcts"}
            else:
                ladder_part = await _call_place_tp_ladder(symbol, side, pcts, splits, decision)
                if ladder_part.get("ok"):
                    _last_ladder_at[symbol] = now

    # Breakeven stop
    be_part = await _maybe_set_be(symbol, side, decision)

    out = {
        "ok": bool(ladder_part.get("ok")) and bool(be_part.get("ok")),
        "symbol": symbol,
        "side": side,
        "ladder": ladder_part,
        "breakeven": be_part,
        "policy": {
            "ladder_enable": LADDER_TP_ENABLE,
            "ladder_on_approve": TP_LADDER_ON_APPROVE,
            "stream_tp_be": STREAM_TP_BE,
            "be_offset_bps": decision.get("be_offset_bps", TP_BE_OFFSET_BPS),
            "be_only_after_tp1": decision.get("be_only_after_tp1", TP_BE_ONLY_AFTER_TP1),
            "profit_lock_steps": _env_list_of_floats(PROFIT_LOCK_STEPS),
        },
    }
    return out


