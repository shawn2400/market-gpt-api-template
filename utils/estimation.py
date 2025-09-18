# utils/estimation.py
from __future__ import annotations
import math, statistics
from typing import Dict, Any, List, Tuple, Optional
from datetime import datetime, timezone, timedelta

# נתונים מהלקוח
try:
    from utils.get_klines import get_klines_sync
except Exception:
    def get_klines_sync(symbol: str, interval: str = "15m", limit: int = 120):
        return []

try:
    from utils.binance_client import get_price
except Exception:
    def get_price(symbol: str) -> Optional[float]:
        return None

def _ema(vals: List[float], n: int) -> float:
    if not vals: return float("nan")
    k = 2 / (n + 1)
    ema = vals[0]
    for v in vals[1:]:
        ema = v * k + ema * (1 - k)
    return ema

def _pct(a: float, b: float) -> float:
    if b == 0: return 0.0
    return (a - b) / b

def get_market_context_summary() -> str:
    """סיכום קצר על BTC (עוגן שוק): מגמה (EMA21/50), RSI משוער, ADX פשטני."""
    try:
        kl = get_klines_sync("BTCUSDT", interval="15m", limit=120)
        closes = [float(x[4]) for x in kl] if kl else []
        if len(closes) < 50:
            return "BTC: —"
        ema21 = _ema(closes[-100:], 21)
        ema50 = _ema(closes[-100:], 50)
        trend = "שורי ⬆️" if ema21 > ema50 else "דובי ⬇️"
        # RSI קצר (14) גס:
        deltas = [closes[i]-closes[i-1] for i in range(1,len(closes))]
        gains = [d for d in deltas[-14:] if d>0]
        losses= [-d for d in deltas[-14:] if d<0]
        avg_gain = sum(gains)/14 if len(gains)==14 else (sum(gains)/max(1,len(gains)))
        avg_loss = sum(losses)/14 if len(losses)==14 else (sum(losses)/max(1,len(losses)))
        rs = (avg_gain/avg_loss) if avg_loss>0 else 999
        rsi = 100 - (100/(1+rs))
        # ADX גס (נשמור לפשטות כסטיית תקן/תנודתיות יחסית)
        vol = statistics.pstdev(closes[-30:]) / (sum(closes[-30:])/30) * 100 if len(closes)>=30 else 0
        return f"BTC {trend} · RSI≈{rsi:.1f} · Vol≈{vol:.1f}%"
    except Exception:
        return "BTC: —"

async def estimate_trade_meta(plan: Dict[str, Any]) -> Dict[str, Any]:
    """הערכות קלות משקל — מספיקות להצגה בטלגרם, לא לשערוך ביצועי אמת."""
    out: Dict[str, Any] = {"probs":{}, "eta":{}}
    try:
        entry = float(plan.get("entry_price") or plan.get("price") or 0)
        side  = str(plan.get("side","")).upper()
        lev   = float(plan.get("leverage") or 0)
        budget = float(plan.get("budget_usd") or plan.get("budget") or 0)
        now_px = plan.get("now_price") or get_price(str(plan.get("symbol","")).upper())
        now_px = float(now_px) if now_px else entry
        tp_legs = plan.get("tp") or plan.get("tp_orders") or []

        # ETA פשטני: לכל TP נוסיף 5–20 דקות בהתאם למרחק מהמחיר
        for i, leg in enumerate(tp_legs, start=1):
            px = float(leg.get("stopPrice") or leg.get("price") or 0)
            dist = abs(px - now_px) / max(1e-9, now_px)
            eta_min = min(180, max(2, int(dist * 60 * 10)))  # 2–180 דקות
            out["eta"][f"tp{i}"] = eta_min * 60

        out["eta"]["entry_sec"] = 60 if (plan.get("order_type","MARKET").upper()=="MARKET") else 300

        # הסתברויות פשטניות לפי score + מגמה BTC
        score = float(plan.get("score") or 5.0)
        base_p = 0.45 + (score-5.0)*0.05  # כל נקודה מעל 5 מוסיפה ~5%
        base_p = max(0.2, min(0.85, base_p))
        # שיפוע קטן לפי התאמת מגמת BTC
        mc = get_market_context_summary()
        bull = ("⬆️" in mc)
        if (side in ("BUY","LONG") and bull) or (side in ("SELL","SHORT") and not bull):
            base_p += 0.05
        out["probs"]["overall"] = max(0.2, min(0.9, base_p))

        # חלוקה ל־TP1/2/3 יורד מעט כלפי מעלה
        out["probs"]["tp1"] = max(0.3, min(0.95, base_p + 0.10))
        out["probs"]["tp2"] = max(0.2, min(0.90, base_p + 0.00))
        out["probs"]["tp3"] = max(0.1, min(0.80, base_p - 0.10))

        # ציפיית PnL משוערת (שמרני: חצי מה־TP2 * תקציב * מינוף)
        if tp_legs:
            tp2 = float(tp_legs[min(1,len(tp_legs))-1].get("stopPrice") or tp_legs[min(1,len(tp_legs))-1].get("price") or entry)
            pct = abs(tp2-entry)/max(entry,1e-9)
            out["expected_pnl_usd"] = budget * pct * max(1.0, lev) * 0.5
        else:
            out["expected_pnl_usd"] = budget * 0.02 * max(1.0, lev) * 0.5

    except Exception:
        pass
    return out

