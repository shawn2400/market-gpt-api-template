# -*- coding: utf-8 -*-
from __future__ import annotations
from typing import Dict, Any

def decide_manage_mode(ind: Dict[str, float]) -> str:
    """
    מחזיר אחד: 'BASE','AGGR','DEF'
    - BASE: ברירת מחדל
    - AGGR: שוק אגרסיבי (ADX גבוה, ATR% גבוה) -> trail יותר הדוק, TP קרובים יותר
    - DEF : שוק עדין/צ׳ופי -> BE רחוק קלות, TP רחוקים יותר
    """
    adx = float(ind.get("adx", 0.0))
    atr = float(ind.get("atr", 0.0))
    price = float(ind.get("price", 0.0))
    atr_pct = (atr / price) * 100.0 if price > 0 else 0.0

    if adx >= 28 or atr_pct >= 0.9:
        return "AGGR"
    if adx < 16 or atr_pct < 0.3:
        return "DEF"
    return "BASE"

def tweak_profile(profile: Dict[str, Any], mode: str) -> Dict[str, Any]:
    """
    משנה את offset_bps/pcts/splits/atr_mult לפי mode.
    שמרני, לא שובר אינוואריאנטים.
    """
    p = dict(profile)
    if mode == "AGGR":
        # Trail הדוק יותר, TP קרובים יותר
        if p.get("atr_mult") is not None:
            p["atr_mult"] = max(0.8, float(p["atr_mult"]) * 0.8)
        p["offset_bps"] = max(2, int(p.get("offset_bps", 5)) - 1)
        p["pcts"] = [max(1.0, x * 0.8) for x in p.get("pcts", [4,8,16])]
    elif mode == "DEF":
        # Trail רופף, יותר מרווח ל-BE, TP רחוקים יותר
        if p.get("atr_mult") is not None:
            p["atr_mult"] = float(p["atr_mult"]) * 1.2
        p["offset_bps"] = int(p.get("offset_bps", 5)) + 1
        p["pcts"] = [x * 1.15 for x in p.get("pcts", [4,8,16])]
    return p

