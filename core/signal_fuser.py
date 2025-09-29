# core/signal_fuser.py
from __future__ import annotations
from typing import Dict, Any, List
from utils.indicators_registry import run_all
from utils.gates import btc_gate_ok, squeeze_gate_ok, quality_ok, exposure_ok, symbol_cooldown_ok
from utils.config import cfg

def fuse_signals(df, *, symbol:str, tf:str) -> Dict[str,Any]:
    # הרצת כל האינדיקטורים
    res = run_all(df, symbol=symbol, tf=tf)
    signals: List[Dict[str,Any]] = []
    ctx = {}

    # איחוד – דוגמה: MC-B/QQE/Alpha/SMC/Invictus
    for key in ("mc_b","qqe","alpha","smc","invictus"):
        r = res.get(key) or {}
        for s in (r.get("signals") or []):
            # Normalize
            signals.append({
                "name": key, "ts": s.get("ts"),
                "side": s.get("side"), "strength": s.get("strength", 0),
                "reason": s.get("reason", {})
            })
    # בוחרים אות מוביל (לפי strength/priority)
    signals.sort(key=lambda x: x["strength"], reverse=True)
    lead = signals[0] if signals else None

    if not lead:
        return {"ok": False, "reason": "no_signal", "indicators": res}

    side = lead["side"]
    # Gates (דוגמה; הוסף OI/Funding/Basis לפי זמינותך)
    if cfg.BTC_GATE_ENABLE and not btc_gate_ok(side): return {"ok": False, "reason": "btc_gate", "indicators": res}
    if cfg.SQUEEZE_GATE_ENABLE and not squeeze_gate_ok(symbol): return {"ok": False, "reason": "squeeze_gate", "indicators": res}
    if not symbol_cooldown_ok(symbol): return {"ok": False, "reason": "symbol_cooldown", "indicators": res}
    if not exposure_ok(symbol): return {"ok": False, "reason": "exposure_cap", "indicators": res}

    # איכות: נבנה ציון משולב (אפשר להחליף בציון שלך)
    quality = min(10.0, lead["strength"])
    if not quality_ok(quality, cfg.MIN_QUALITY_SCORE):
        return {"ok": False, "reason": "quality_low", "indicators": res}

    # רמות – לדוגמה מ-Alpha/Chandelier/ATR
    alpha = res.get("alpha", {})
    atr = alpha.get("series", {}).get("atr")
    px = float(df["close"].iloc[-1])
    atr_val = float(atr.iloc[-1]) if atr is not None else 0.0
    sl = px - 1.5*atr_val if side=="long" else px + 1.5*atr_val
    tp1= px + 1.8*atr_val if side=="long" else px - 1.8*atr_val
    tp2= px + 3.2*atr_val if side=="long" else px - 3.2*atr_val

    return {"ok": True, "side": side, "entry": px, "sl": sl, "tp1": tp1, "tp2": tp2,
            "quality": quality, "context": {"lead": lead, "tf": tf}, "indicators": res}
