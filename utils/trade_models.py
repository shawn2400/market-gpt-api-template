# utils/trade_models.py
from __future__ import annotations
from typing import Optional, Dict, Any
from dataclasses import dataclass, asdict
from datetime import datetime
import pytz

__all__ = ["TradeProposal", "TradeETA", "summarize"]

@dataclass
class TradeProposal:
    symbol: str
    side: str
    entry: float
    sl: float
    tp1: float
    tp2: Optional[float] = None
    tp3: Optional[float] = None
    leverage: int = 10
    budget_usd: float = 50.0
    success_pct: Optional[float] = None
    current_price: Optional[float] = None

    def notional_usd(self) -> float:
        return float(self.budget_usd) * float(self.leverage)

    def qty_estimate(self) -> float:
        if self.entry <= 0:
            return 0.0
        return self.notional_usd() / float(self.entry)

    def risk_rr(self) -> Dict[str, Any]:
        rr: Dict[str, Any] = {}
        if self.sl and self.entry:
            risk = abs(self.entry - self.sl)
            if risk > 0:
                rr["rr1"] = abs(self.tp1 - self.entry) / risk if self.tp1 else None
                rr["rr2"] = abs(self.tp2 - self.entry) / risk if self.tp2 else None
                rr["rr3"] = abs(self.tp3 - self.entry) / risk if self.tp3 else None
        return rr

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)

@dataclass
class TradeETA:
    tz: str = "Asia/Jerusalem"
    now_local: str = ""
    eta_sl: Optional[str] = None
    eta_tp1: Optional[str] = None
    eta_tp2: Optional[str] = None
    eta_tp3: Optional[str] = None

    @classmethod
    def make(cls) -> "TradeETA":
        tzname = "Asia/Jerusalem"
        now_local = datetime.now(pytz.timezone(tzname)).strftime("%Y-%m-%d %H:%M:%S")
        return cls(tz=tzname, now_local=now_local)

def summarize(tp: TradeProposal, eta: TradeETA, why: str = "") -> str:
    rr = tp.risk_rr()
    rr1_s = f"{rr['rr1']:.2f}" if rr.get("rr1") else "—"
    rr2_s = f"{rr['rr2']:.2f}" if rr.get("rr2") else "—"
    rr3_s = f"{rr['rr3']:.2f}" if rr.get("rr3") else "—"

    line_rr = f"RR: TP1 `{rr1_s}`"
    if tp.tp2:
        line_rr += f" | TP2 `{rr2_s}`"
    if tp.tp3:
        line_rr += f" | TP3 `{rr3_s}`"

    price_now = f"{tp.current_price:.4f}" if (tp.current_price or 0) > 0 else "—"

    parts = [
        "🧠 *AlgoGPT — הצעת טרייד*",
        f"*{tp.symbol}* | *{tp.side.upper()}* | מחיר עכשיו: `{price_now}`",
        " | ".join(
            [f"כניסה: `{tp.entry:.4f}`", f"SL: `{tp.sl:.4f}`", f"TP1: `{tp.tp1:.4f}`"]
            + ([f"TP2: `{tp.tp2:.4f}`"] if tp.tp2 else [])
            + ([f"TP3: `{tp.tp3:.4f}`"] if tp.tp3 else [])
        ),
        f"מינוף: `x{tp.leverage}` | תקציב: `${tp.budget_usd:.2f}` | "
        f"Notional≈ `${tp.notional_usd():.2f}` | Qty≈ `{tp.qty_estimate():.6f}`",
        line_rr,
        (f"% הצלחה משוער: `{tp.success_pct:.1f}%`" if tp.success_pct else ""),
        f"⏱️ *זמנים* (TZ={eta.tz}) — עכשיו: _{eta.now_local}_",
        " | ".join(
            [f"ETA → SL: _{eta.eta_sl or '—'}_", f"TP1: _{eta.eta_tp1 or '—'}_"]
            + ([f"TP2: _{eta.eta_tp2}_"] if eta.eta_tp2 else [])
            + ([f"TP3: _{eta.eta_tp3}_"] if eta.eta_tp3 else [])
        ),
        (f"סיבה/תקציר: {why}" if why else ""),
    ]
    return "\n".join([p for p in parts if p])
















