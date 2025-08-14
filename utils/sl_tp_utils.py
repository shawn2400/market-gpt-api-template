from typing import Tuple, Optional
import math

# ננסה לקרוא פרמטרים מקובץ הקונפיג; יש פולבק לערכי דיפולט אם חסר.
try:
    from utils import config
    _CFG_MIN_PCT_FLOOR = float(getattr(config, "SLTP_MIN_PCT_FLOOR", 0.003))  # 0.3%
    _CFG_TP_PCT_FLOOR  = float(getattr(config, "SLTP_TP_PCT_FLOOR", 0.006))  # 0.6%
    _CFG_ATR_SL_MULT   = float(getattr(config, "SLTP_ATR_SL_MULT", 1.5))
    _CFG_ATR_TP_MULT   = float(getattr(config, "SLTP_ATR_TP_MULT", 2.5))
except Exception:
    _CFG_MIN_PCT_FLOOR = 0.003
    _CFG_TP_PCT_FLOOR  = 0.006
    _CFG_ATR_SL_MULT   = 1.5
    _CFG_ATR_TP_MULT   = 2.5

def _to_float(x, default: float = 0.0) -> float:
    try:
        v = float(x)
        if math.isnan(v) or math.isinf(v):
            return float(default)
        return v
    except Exception:
        return float(default)

def _clamp(x: float, lo: float, hi: float) -> float:
    if lo > hi:
        lo, hi = hi, lo
    return max(lo, min(hi, x))

def _norm_dir(direction: str) -> str:
    d = (direction or "").strip().upper()
    if d in ("LONG", "BUY"):
        return "LONG"
    if d in ("SHORT", "SELL"):
        return "SHORT"
    return "SHORT"

def get_sltp_params() -> dict:
    return {
        "min_pct_floor": float(_CFG_MIN_PCT_FLOOR),
        "tp_pct_floor": float(_CFG_TP_PCT_FLOOR),
        "atr_sl_mult": float(_CFG_ATR_SL_MULT),
        "atr_tp_mult": float(_CFG_ATR_TP_MULT),
    }

def calculate_sl_tp(
    entry_price: float,
    direction: str,
    atr: Optional[float] = None,
    *,
    min_pct_floor: Optional[float] = None,
    tp_pct_floor: Optional[float] = None,
    atr_sl_mult: Optional[float] = None,
    atr_tp_mult: Optional[float] = None,
) -> Tuple[float, float]:
    entry = _to_float(entry_price)
    if entry <= 0:
        raise ValueError("entry_price must be positive")

    min_pct = _to_float(min_pct_floor, _CFG_MIN_PCT_FLOOR)
    tp_pct  = _to_float(tp_pct_floor,  _CFG_TP_PCT_FLOOR)
    slm     = _to_float(atr_sl_mult,   _CFG_ATR_SL_MULT)
    tpm     = _to_float(atr_tp_mult,   _CFG_ATR_TP_MULT)

    min_pct = _clamp(min_pct if min_pct > 0 else _CFG_MIN_PCT_FLOOR, 0.0005, 0.15)
    tp_pct  = _clamp(tp_pct  if tp_pct  > 0 else _CFG_TP_PCT_FLOOR,  0.0005, 0.25)
    slm     = _clamp(slm     if slm     > 0 else _CFG_ATR_SL_MULT,   0.2,    10.0)
    tpm     = _clamp(tpm     if tpm     > 0 else _CFG_ATR_TP_MULT,   0.2,    15.0)

    d = _norm_dir(direction)
    use_atr = _to_float(atr, 0.0) if atr is not None else 0.0
    if use_atr > 0:
        sl_off = max(use_atr * slm, entry * min_pct)
        tp_off = max(use_atr * tpm, entry * tp_pct)
    else:
        sl_off = entry * min_pct
        tp_off = entry * tp_pct

    if d == "LONG":
        sl = entry - sl_off
        tp = entry + tp_off
        if sl >= entry:
            sl = entry * (1 - min_pct)
        if tp <= entry:
            tp = entry * (1 + tp_pct)
    else:  # SHORT
        sl = entry + sl_off
        tp = entry - tp_off
        if sl <= entry:
            sl = entry * (1 + min_pct)
        if tp >= entry:
            tp = entry * (1 - tp_pct)

    return (round(float(sl), 6), round(float(tp), 6))





       






