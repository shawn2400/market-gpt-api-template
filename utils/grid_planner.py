# utils/grid_planner.py
from __future__ import annotations
import math

def plan_grid(price: float, budget_usd: float, levels: int = 6, step_pct: float = 0.8, side: str = "LONG"):
    """
    מחלק את התקציב פרוגרסיבית על פני רמות, מרווח קבוע באחוזים.
    side: LONG (קונה בירידות), SHORT (מוכר בעליות)
    """
    side = side.upper()
    lvls = max(2, int(levels))
    step = abs(step_pct) / 100.0
    # חלוקה פרוגרסיבית קלה (יותר משקל בתחתית ב-Long)
    weights = [1.1**i for i in range(lvls)][::-1] if side=="LONG" else [1.1**i for i in range(lvls)]
    s = sum(weights)
    weights = [w/s for w in weights]
    entries = []
    for i in range(lvls):
        off = (i+1)*step
        lvl_price = price * (1.0 - off if side=="LONG" else 1.0 + off)
        entries.append({"level": i+1, "price": lvl_price, "alloc_usd": budget_usd*weights[i]})
    # TP/SL בסיסי: TP כללית ~ price*(1 ± 2*step), SL ~ price*(1 ∓ 2.5*step)
    tp = price * (1.0 + 2*step if side=="LONG" else 1.0 - 2*step)
    sl = price * (1.0 - 2.5*step if side=="LONG" else 1.0 + 2.5*step)
    return {"side": side, "spot_price": price, "levels": entries, "tp": tp, "sl": sl}
