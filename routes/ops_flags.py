# routes/ops_flags.py
from __future__ import annotations
import re
from typing import Dict, Any, Optional, List

# ---------- Small helpers ----------
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

def _search(rx: re.Pattern, text: str) -> Optional[str]:
    m = rx.search(text or "")
    return m.group(1) if m else None

# ---------- Regex bank ----------
RX_MODE           = re.compile(r"\[mode:\s*(MARKET|HYBRID|AUTO)\s*\]", re.I)

# TP family
RX_TPKIND         = re.compile(r"\bTPKIND\s*:\s*([A-Z_]+)\b", re.I)
RX_TPSPLIT        = re.compile(r"\bTPSPLIT\s*:\s*([0-9\.\,\s]+)\b", re.I)
RX_TPSPLITPCT     = re.compile(r"\bTPSPLITPCT\s*:\s*([0-9\.\,\s]+)\b", re.I)

# Entry / offsets
RX_ENTRY          = re.compile(r"\bENTRY\s*:\s*(MARKET|LIMIT)\b", re.I)
RX_ENTRY_OFFSET   = re.compile(r"\bENTRY_OFFSET\s*:\s*([\-+]?[0-9]+(?:\.[0-9]+)?)\b", re.I)
RX_TP_OFFSET      = re.compile(r"\bTP_OFFSET\s*:\s*([\-+]?[0-9]+(?:\.[0-9]+)?)\b", re.I)
RX_SL_OFFSET      = re.compile(r"\bSL_OFFSET\s*:\s*([\-+]?[0-9]+(?:\.[0-9]+)?)\b", re.I)

# Reduce-only
RX_REDUCE         = re.compile(r"\bREDUCE(?:\s*:\s*(ON|OFF))?\b", re.I)

# Positioning
RX_POSITION_SIDE  = re.compile(r"\bPOSITION_SIDE\s*:\s*(LONG|SHORT|BOTH)\b", re.I)
RX_POSITION_MODE  = re.compile(r"\bPOSITION_MODE\s*:\s*(HEDGE|ONE[_\- ]?WAY)\b", re.I)

# Trailing stop family
RX_TRAIL          = re.compile(r"\bTRAIL(?:ING)?(?:_ENABLE)?\s*:\s*(ON|OFF|TRUE|FALSE|1|0)\b", re.I)
RX_TRAIL_MULT     = re.compile(r"\bTRAIL_(?:MULT|ATR_MULT)\s*:\s*([0-9]+(?:\.[0-9]+)?)\b", re.I)
RX_TRAIL_FREEZE   = re.compile(r"\bTRAIL_FREEZE(?:_ENABLE)?\s*:\s*(ON|OFF|TRUE|FALSE|1|0)\b", re.I)

# RR guard (אופציונלי)
RX_RR_MIN         = re.compile(r"\bRR_MIN\s*:\s*([0-9]+(?:\.[0-9]+)?)\b", re.I)

# ---------- Public API ----------
def apply_note_flags(note: Optional[str], ticket: Dict[str, Any]) -> Dict[str, Any]:
    """
    Enrich trade ticket with flags parsed from free-text 'note'.
    Never raises; only adds/overrides known fields.
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
        ticket["tp_kind"] = tpkind.upper()  # e.g. LIMIT / TAKE_PROFIT / TAKE_PROFIT_MARKET

    tps = _search(RX_TPSPLIT, text)
    if tps:
        arr = _parse_csv_floats(tps)
        if arr: ticket["tp_splits"] = arr

    tpspct = _search(RX_TPSPLITPCT, text)
    if tpspct:
        arr = _parse_csv_floats(tpspct)
        if arr: ticket["tp_splits_pct"] = arr  # אם יש תמיכה בשכבה מעל

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
        ticket["reduce_only"] = (reduce_val.upper() in ("ON","TRUE","1"))

    # --- Positioning ---
    ps = _search(RX_POSITION_SIDE, text)
    if ps:
        ticket["position_side"] = ps.upper()  # LONG | SHORT | BOTH

    pm = _search(RX_POSITION_MODE, text)
    if pm:
        # מידע/בקרה; ההחלטה בפועל נעשית לפי HEDGE_MODE ב-ENV וה-Executor
        norm = pm.upper().replace(" ", "").replace("-", "")
        ticket["position_mode"] = "HEDGE" if norm == "HEDGE" else "ONE_WAY"

    # --- Trailing stop family ---
    tr = _search(RX_TRAIL, text)  # ON|OFF|TRUE|FALSE|1|0
    if tr:
        ticket["trail"] = (str(tr).strip().lower() in ("on","true","1"))

    trm = _search(RX_TRAIL_MULT, text)  # float
    if trm:
        fm = _parse_float(trm)
        if fm is not None:
            # ENV אצלך: TRAIL_ATR_MULT; נשים גם alias שמיועד ל-Executor
            ticket["trail_atr_mult"] = fm
            ticket["trail_mult"] = fm

    trf = _search(RX_TRAIL_FREEZE, text)  # ON|OFF|TRUE|FALSE|1|0
    if trf:
        ticket["trail_freeze"] = (str(trf).strip().lower() in ("on","true","1"))

    # --- RR guard (metadata; enforcement שכבה אחרת) ---
    rr = _search(RX_RR_MIN, text)
    if rr:
        rv = _parse_float(rr)
        if rv is not None:
            ticket["rr_min"] = rv

    return ticket



