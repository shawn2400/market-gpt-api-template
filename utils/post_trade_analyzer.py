# utils/post_trade_analyzer.py
from __future__ import annotations
import os, json, logging, math
from pathlib import Path
from typing import Dict, Any, Optional

logger = logging.getLogger("algogpt.post_trade_analyzer")

REVIEW_PATH = Path("static/cache/trade_reviews.jsonl")
REVIEW_PATH.parent.mkdir(parents=True, exist_ok=True)

try:
    from utils.telegram_notifier import notify_trade_review
except Exception:
    async def notify_trade_review(symbol: str, review: str):
        return None  # fallback no-op

def _grade_from_rr(rr: float, pnl_usd: float) -> str:
    if rr >= 2.0 and pnl_usd > 0: return "A"
    if rr >= 1.3 and pnl_usd > 0: return "B"
    if rr >= 1.0: return "C"
    return "D"

def _fmt_suggestion(rr: float, took_sl: bool, tp_hit: bool) -> str:
    sug = []
    if took_sl and rr < 1.0:
        sug.append("שקול SL רחב יותר (ATR×1.8) או כניסה מדוייקת יותר (Hybrid).")
    if tp_hit and rr < 1.3:
        sug.append("אפשר לשקול הגדלת TP1/Trailing אם ADX>25 ומומנטום חיובי.")
    if not tp_hit and not took_sl:
        sug.append("יתכן ויציאה ידנית מוקדמת היתה מתונה מדי; בדוק Chop detection.")
    if not sug:
        sug.append("ניהול סדיר. המשך במעקב.")
    return " ".join(sug)

def analyze_trade_result(
    *, symbol: str, side: str,
    entry_price: float, exit_price: float,
    sl_price: Optional[float] = None,
    tp_price: Optional[float] = None,
    pnl_usd: float = 0.0,
    atr_at_entry: Optional[float] = None,
    adx_at_entry: Optional[float] = None,
    duration_min: Optional[float] = None
) -> Dict[str, Any]:
    try:
        rr = 0.0
        if sl_price and sl_price > 0:
            if side.upper()=="LONG":
                rr = abs((exit_price - entry_price) / max(entry_price - sl_price, 1e-9))
            else:
                rr = abs((entry_price - exit_price) / max(sl_price - entry_price, 1e-9))
        tp_hit = (tp_price and ((side.upper()=="LONG" and exit_price>=tp_price) or (side.upper()=="SHORT" and exit_price<=tp_price))) or False
        took_sl = (sl_price and ((side.upper()=="LONG" and exit_price<=sl_price) or (side.upper()=="SHORT" and exit_price>=sl_price))) or False

        grade = _grade_from_rr(rr, pnl_usd)
        suggestion = _fmt_suggestion(rr, bool(took_sl), bool(tp_hit))

        review = {
            "symbol": symbol.upper(),
            "side": side.upper(),
            "entry": entry_price,
            "exit": exit_price,
            "sl": sl_price,
            "tp": tp_price,
            "rr": round(rr, 2),
            "pnl_usd": round(float(pnl_usd), 2),
            "grade": grade,
            "adx_entry": adx_at_entry,
            "atr_entry": atr_at_entry,
            "duration_min": duration_min,
        }
        return {"ok": True, "review": review, "insight": suggestion}
    except Exception as e:
        logger.warning("post_trade_analyzer failed: %s", e)
        return {"ok": False, "error": str(e)}

def _write_review_line(payload: Dict[str, Any]) -> None:
    try:
        with REVIEW_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except Exception as e:
        logger.warning("write review failed: %s", e)

async def analyze_and_notify(summary: Dict[str, Any]) -> Dict[str, Any]:
    """
    summary דוגמה:
    {
      "symbol": "BTCUSDT", "side":"LONG",
      "entry": 62000.0, "exit": 62620.0,
      "sl": 61500.0, "tp": 62800.0,
      "pnl_usd": 42.5, "atr_entry": 120.0, "adx_entry": 27.0, "duration_min": 37
    }
    """
    res = analyze_trade_result(
        symbol=summary.get("symbol",""),
        side=summary.get("side",""),
        entry_price=float(summary.get("entry") or 0),
        exit_price=float(summary.get("exit") or 0),
        sl_price=summary.get("sl"),
        tp_price=summary.get("tp"),
        pnl_usd=float(summary.get("pnl_usd") or 0),
        atr_at_entry=summary.get("atr_entry"),
        adx_at_entry=summary.get("adx_entry"),
        duration_min=summary.get("duration_min"),
    )
    if res.get("ok"):
        payload = {"review": res["review"], "insight": res["insight"]}
        _write_review_line(payload)
        try:
            await notify_trade_review(summary.get("symbol",""), res["insight"])
        except Exception:
            pass
    return res
