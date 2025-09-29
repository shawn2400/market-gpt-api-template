# routes/ops_flags.py
from __future__ import annotations
import re
from typing import Dict, Any, Optional
from fastapi import APIRouter, Body

router = APIRouter(tags=["ops-flags"])

RX_MODE    = re.compile(r"\bmode\s*:\s*(MARKET|HYBRID|AUTO)\b", re.I)
RX_TPKIND  = re.compile(r"\bTPKIND\s*:\s*(TAKE_PROFIT|TAKE_PROFIT_MARKET|LIMIT|MARKET)\b", re.I)
RX_TPSPLIT = re.compile(r"\bTPSPLIT\s*:\s*([0-9., ]+)\b", re.I)
RX_TPSPLITPCT = re.compile(r"\bTPSPLITPCT\s*:\s*([0-9., ]+)\b", re.I)
RX_SLKIND  = re.compile(r"\bSLKIND\s*:\s*(STOP|STOP_MARKET|MARKET|LIMIT)\b", re.I)
RX_REDUCE  = re.compile(r"\bREDUCE(_ONLY)?\b", re.I)
RX_ENTRY   = re.compile(r"\bENTRY\s*:\s*(LIMIT|MARKET)\b", re.I)
RX_OFFS    = re.compile(r"\b(ENTRY_OFFSET|TP_OFFSET|SL_OFFSET)\s*:\s*([-+]?\d+(?:\.\d+)?)\b", re.I)
RX_RRMIN   = re.compile(r"\bRR_MIN\s*:\s*([0-9]+(?:\.[0-9]+)?)\b", re.I)
RX_POSSIDE = re.compile(r"\bPOS(ITION)?_?SIDE\s*:\s*(LONG|SHORT|BOTH)\b", re.I)

def _float_list(s: str) -> Optional[list]:
    try:
        arr = [float(x.strip()) for x in s.split(",") if x.strip() != ""]
        return arr if arr else None
    except Exception:
        return None

def apply_note_flags(note: Optional[str], ticket: Dict[str, Any]) -> Dict[str, Any]:
    if not note:
        return ticket

    txt = str(note)

    m = RX_TPKIND.search(txt)
    if m:
        val = m.group(1).upper()
        if val == "LIMIT":  val = "TAKE_PROFIT"
        if val == "MARKET": val = "TAKE_PROFIT_MARKET"
        ticket["tp_kind"] = val

    m = RX_TPSPLIT.search(txt)
    if m:
        arr = _float_list(m.group(1))
        if arr: ticket["tp_splits"] = arr

    m = RX_TPSPLITPCT.search(txt)
    if m:
        arr = _float_list(m.group(1))
        if arr:
            s = sum(arr)
            if s > 0:
                ticket["tp_splits"] = [round(x/s, 6) for x in arr]

    m = RX_SLKIND.search(txt)
    if m:
        val = m.group(1).upper()
        if val == "MARKET": val = "STOP_MARKET"
        ticket["sl_kind"] = val

    if RX_REDUCE.search(txt):
        ticket["reduce_only"] = True

    m = RX_ENTRY.search(txt)
    if m:
        ticket["entry_kind"] = m.group(1).upper()

    for m in RX_OFFS.finditer(txt):
        key = m.group(1).upper()
        val = float(m.group(2))
        if key == "ENTRY_OFFSET": ticket["entry_offset"] = val
        elif key == "TP_OFFSET":  ticket["tp_offset"] = val
        elif key == "SL_OFFSET":  ticket["sl_offset"] = val

    m = RX_RRMIN.search(txt)
    if m:
        try:
            ticket["rr_min"] = float(m.group(1))
        except Exception:
            pass

    m = RX_POSSIDE.search(txt)
    if m:
        ticket["position_side"] = m.group(2).upper()

    return ticket

@router.post("/ops/flags/parse", summary="Parse advanced flags from note")
async def parse_flags(payload: Dict[str, Any] = Body(...)):
    note = payload.get("note")
    ticket = payload.get("ticket") or {}
    return {"ok": True, "ticket": apply_note_flags(note, ticket)}

