# routes/ops_flags.py
from __future__ import annotations
from typing import Dict, Any, Optional, Tuple, List
import re

"""
Parser לדגלים בתוך note, למשל:
    "[mode: HYBRID] MARKET+REDUCE TPKIND:LIMIT TPSPLIT:0.5,0.3,0.2 SLKIND:STOP LIMITOFF:BPS=8"
כללי:
- תג mode סטנדרטי נשמר (MARKET/HYBRID/AUTO)
- דגלים חופשיים: REDUCE, CLOSE_HALF, CLOSE_ALL, REVERSE
- מפתחות עם ערכים: TPKIND:(LIMIT|MARKET|TAKE_PROFIT), SLKIND:(STOP|STOP_MARKET), TPSPLIT:0.5,0.3,0.2
- OFFSETים: TP_OFFSET_BPS=8, SL_OFFSET_BPS=8, LIMITOFF:BPS=8

פלט:
{
  "mode": "HYBRID",
  "reduce_only": True,
  "tp_kind": "LIMIT",
  "sl_kind": "STOP",
  "tp_splits": [0.5, 0.3, 0.2],
  "tp_offset_bps": 8,
  "sl_offset_bps": 8,
  "limit_offset_bps": 8,
  "op": null|"CLOSE_HALF"|"CLOSE_ALL"|"REVERSE"
}
"""

_MODE_RE = re.compile(r"\[mode:\s*(MARKET|HYBRID|AUTO)\s*\]", re.I)

def _to_float_list(v: str) -> Optional[List[float]]:
    try:
        xs = [float(x.strip()) for x in v.split(",") if x.strip() != ""]
        if xs and abs(sum(xs) - 1.0) < 1e-6:
            return xs
        # אם לא סכום=1, עדיין נאפשר – המבצע יקבע יחסי.
        return xs if xs else None
    except Exception:
        return None

def parse_note_flags(note: Optional[str]) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "mode": None,
        "reduce_only": False,
        "tp_kind": None,
        "sl_kind": None,
        "tp_splits": None,
        "tp_offset_bps": None,
        "sl_offset_bps": None,
        "limit_offset_bps": None,
        "op": None,
    }
    if not note:
        return out

    s = str(note)

    # mode
    m = _MODE_RE.search(s)
    if m:
        out["mode"] = m.group(1).upper()

    # flags (space-separated)
    upper = s.upper()

    # operations
    if "CLOSE_HALF" in upper:
        out["op"] = "CLOSE_HALF"
    elif "CLOSE_ALL" in upper:
        out["op"] = "CLOSE_ALL"
    elif "REVERSE" in upper:
        out["op"] = "REVERSE"

    # simple flags
    if "REDUCE" in upper or "REDUCE_ONLY" in upper:
        out["reduce_only"] = True

    # key:value patterns (TPKIND, SLKIND)
    m_tpk = re.search(r"\bTPKIND\s*:\s*([A-Z_]+)\b", s, flags=re.I)
    if m_tpk:
        out["tp_kind"] = m_tpk.group(1).upper()

    m_slk = re.search(r"\bSLKIND\s*:\s*([A-Z_]+)\b", s, flags=re.I)
    if m_slk:
        out["sl_kind"] = m_slk.group(1).upper()

    m_tps = re.search(r"\bTPSPLIT\s*:\s*([0-9\., ]+)\b", s, flags=re.I)
    if m_tps:
        out["tp_splits"] = _to_float_list(m_tps.group(1))

    # offsets: TP_OFFSET_BPS=8, SL_OFFSET_BPS=8
    m_tp_off = re.search(r"\bTP_OFFSET_BPS\s*=\s*([0-9]+)\b", s, flags=re.I)
    if m_tp_off:
        out["tp_offset_bps"] = int(m_tp_off.group(1))

    m_sl_off = re.search(r"\bSL_OFFSET_BPS\s*=\s*([0-9]+)\b", s, flags=re.I)
    if m_sl_off:
        out["sl_offset_bps"] = int(m_sl_off.group(1))

    # generic: LIMITOFF:BPS=8  (alias ל-limit_offset_bps)
    m_lim_off = re.search(r"\bLIMITOFF\s*:\s*BPS\s*=\s*([0-9]+)\b", s, flags=re.I)
    if m_lim_off:
        out["limit_offset_bps"] = int(m_lim_off.group(1))

    return out
