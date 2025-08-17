# utils/quantity_utils.py
from __future__ import annotations

# — תאימות לאחור: מאפשר import compute_quality מתוך הקובץ הזה —
from utils.quality import compute_quality  # re-export

# — ה־core ההיסטורי לכמויות לא חובה; משאירים סטאבים כדי ש-fallback ב-calculate_quantity יעבוד —
def get_precision_info(symbol: str):
    raise NotImplementedError("core quantity utils not provided in this build")

def round_step(value: float, step: float) -> float:
    raise NotImplementedError("core quantity utils not provided in this build")

def round_tick(price: float, tick_size: float) -> float:
    raise NotImplementedError("core quantity utils not provided in this build")

def calculate_quantity(symbol: str, entry_price: float, leverage: float, budget_usdt: float) -> float:
    raise NotImplementedError("core quantity utils not provided in this build")














