# routes/ops_flags.py
from __future__ import annotations
import os, re
from typing import Dict, Any, Optional, List

# ---------- Helpers ----------
def _to_bool_flag(v: Optional[str]) -> Optional[bool]:
    if v is None: return None
    s = str(v).strip().lower()
    if s in ("1","true","on","yes"): return True
    if s in ("0","false","off","no"): return False
    return None

def _parse_float(s: Optional[str]) -> Optional[float]:
    try:
        return float(str(s).strip())
    except Exception:
        return None

def _parse_csv_floats(s: Optional[str]) -> Optional[List[float]]:
    if not s: return None
    try:
        arr = [float(x.strip()) for x in str(s).split(",") if x.strip()!=""]
        return arr if arr else None
    except Exception:
        return None

def _norm_upper(s: Optional[str]) -> Optional[str]:
    return str(s).strip().upper() if s is not None else None

# ---------- Regex bank ----------
RX_MODE           = re.compile(r"\[mode:\s*(MARKET|HYBRID|AUTO)\s*\]", re.I)

RX_TPKIND         = re.compile(r"\bTPKIND\s*:\s*([A-Z_]+)\b", re.I)
RX_TPSPLIT        = re.compile(r"\bTPSPLIT\s*:\s*([0-9\.\,\s]+)\b", re.I)
RX_TPSPLITPCT     = re.compile(r"\bTPSPLITPCT\s*:\s*([0-9\.\,\s]+)\b", re.I)

RX_ENTRY          = re.compile(r"\bENTRY\s*:\s*(MARKET|LIMIT)\b", re.I)
RX_ENTRY_OFFSET   = re.compile(r"\bENTRY_OFFSET\s*:\s*([\-+]?[0-9]+(?:\.[0-9]+)?)\b", re.I)
RX_TP_OFFSET      = re.compile(r"\bTP_OFFSET\s*:\s*([\-+]?[0-9]+(?:\.[0-9]+)?)\b", re.I)
RX_SL_OFFSET      = re.compile(r"\bSL_OFFSET\s*:\s*([\-+]?[0-9]+(?:\.[0-9]+)?)\b", re.I)

RX_REDUCE         = re.compile(r"\bREDUCE(?:\s*:\s*(ON|OFF))?\b", re.I)

RX_POSITION_SIDE  = re.compile(r"\bPOSITION_SIDE\s*:\s*(LONG|SHORT|BOTH)\b", re.I)
RX_POSITION_MODE  = re.compile(r"\bPOSITION_MODE\s*:\s*(HEDGE|ONE_WAY)\b", re.I)

# Trailing stop family
RX_TRAIL          = re.compile(r"\bTRAIL\s*:\s*(ON|OFF)\b", re.I)
RX_TRAIL_MULT     = re.compile(r"\bTRAIL_MULT\s*:\s*([0-9]+(?:\.[0-9]+)?)\b", re.I)
RX_TRAIL_FREEZE   = re.compile(r"\bTRAIL_FREEZE\s*:\s*(ON|OFF)\b", re.I)

RX_RR_MIN         = re.compile(r"\bRR_MIN\s*:\s*([0-9]+(?:\.[0-9]+)?)\b", re.I)

def _search(rx: re.Pattern, text: str) -> Optional[str]:
    m = rx.search(text or "")
    return m.group(1) if m else None

# ---------- Public API ----------
def apply_note_flags(note: Optional[str], ticket: Dict[str, Any]) -> Dict[str, Any]:
    """
    Enrich a trade ticket with flags parsed from free-text 'note'.
    This function NEVER raises; it only adds/overrides known fields.
    """
    if not note:
        return ticket
    text = str(note)

    # --- mode ---
    mode = _search(RX_MODE, text)
    if mode:
        ticket["mode"] = mode.upper()   # MARKET | HYBRID | AUTO

    # --- TP config ---
    tpkind = _search(RX_TPKIND, text)
    if tpkind:
        ticket["tp_kind"] = tpkind.upper()  # e.g. LIMIT / TAKE_PROFIT / etc.

    tps = _search(RX_TPSPLIT, text)
    if tps:
        arr = _parse_csv_floats(tps)
        if arr: ticket["tp_splits"] = arr

    tpspct = _search(RX_TPSPLITPCT, text)
    if tpspct:
        arr = _parse_csv_floats(tpspct)
        if arr: ticket["tp_splits_pct"] = arr  # אופציונלי, אם יש תמיכה

    # --- Entry/offsets ---
    entry = _search(RX_ENTRY, text)
    if entry:
        ticket["entry_kind"] = entry.upper()  # MARKET | LIMIT

    v = _parse_float(_search(RX_ENTRY_OFFSET, text))
    if v is not None: ticket["entry_offset"] = v

    v = _parse_float(_search(RX_TP_OFFSET, text))
    if v is not None: ticket["tp_offset"] = v

    v = _parse_float(_search(RX_SL_OFFSET, text))
    if v is not None: ticket["sl_offset"] = v

    # --- Reduce-only ---
    reduce_val = _search(RX_REDUCE, text)
    if reduce_val is None and RX_REDUCE.search(text):   # "REDUCE" בלי ON/OFF => True
        ticket["reduce_only"] = True
    elif reduce_val is not None:
        ticket["reduce_only"] = (reduce_val.upper() == "ON")

    # --- Positioning ---
    ps = _search(RX_POSITION_SIDE, text)
    if ps:
        ticket["position_side"] = ps.upper()  # LONG | SHORT | BOTH

    pm = _search(RX_POSITION_MODE, text)
    if pm:
        ticket["position_mode"] = pm.upper()  # HEDGE | ONE_WAY (מידע/בקרה — לא חובה ENV)

    # --- Trailing stop family ---
    tr = _search(RX_TRAIL, text)  # ON|OFF
    if tr:
        on = (tr.upper() == "ON")
        ticket["trail"] = on

    trm = _search(RX_TRAIL_MULT, text)  # float
    if trm:
        fm = _parse_float(trm)
        if fm is not None:
            # מיפוי לשם ה-ENV הקיים אצלך: TRAIL_ATR_MULT
            ticket["trail_atr_mult"] = fm
            # וגם נשאיר alias כללי "trail_mult" עבור עתיד/קוד אחר
            ticket["trail_mult"] = fm

    trf = _search(RX_TRAIL_FREEZE, text)  # ON|OFF
    if trf:
        ticket["trail_freeze"] = (trf.upper() == "ON")

    # --- RR guard (רק סימון, האכיפה אצלך בלייר approve) ---
    rr = _search(RX_RR_MIN, text)
    if rr:
        rv = _parse_float(rr)
        if rv is not None:
            ticket["rr_min"] = rv

    return ticket


