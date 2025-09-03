# utils/trade_models.py
from __future__ import annotations
from pydantic import BaseModel, Field, validator
from typing import Optional, Dict
from zoneinfo import ZoneInfo
import os, datetime as dt

TZ = os.getenv("TZ", "Asia/Jerusalem")

class TradeProposal(BaseModel):
    symbol: str = Field(..., min_length=6, max_length=20)
    side: str = Field(..., regex=r"^(?i:LONG|SHORT)$")
    current_price: Optional[float] = Field(None, gt=0)
    leverage: int = Field(10, ge=1, le=125)
    entry: float = Field(..., gt=0)
    sl: float = Field(..., gt=0)
    tp1: float = Field(..., gt=0)
    tp2: Optional[float] = Field(None, gt=0)
    tp3: Optional[float] = Field(None, gt=0)
    success_pct: Optional[float] = Field(None, ge=0, le=100)
    budget_usd: float = Field(
        default_factory=lambda: float(os.getenv("DEFAULT_BUDGET_USD", "50")), gt=0
    )

    @validator("symbol")
    def up(cls, v): return v.upper()

    def notional_usd(self) -> float:
        return round(self.budget_usd * self.leverage, 2)

    def qty_estimate(self) -> float:
        return round(self.notional_usd() / self.entry, 6)

    def risk_rr(self) -> Dict[str, float]:
        risk = abs(self.entry - self.sl)
        rr1 = abs(self.tp1 - self.entry) / risk if risk > 0 else 0
        rr2 = abs((self.tp2 or 0) - self.entry) / risk if (risk > 0 and self.tp2) else 0
        rr3 = abs((self.tp3 or 0) - self.entry) / risk if (risk > 0 and self.tp3) else 0
        return {"risk_per_unit": risk, "rr1": rr1, "rr2": rr2, "rr3": rr3}

class TradeETA(BaseModel):
    tz: str = TZ
    now_local: str
    eta_sl: Optional[str] = None
    eta_tp1: Optional[str] = None
    eta_tp2: Optional[str] = None
    eta_tp3: Optional[str] = None
    minutes_sl: Optional[int] = None
    minutes_tp1: Optional[int] = None
    minutes_tp2: Optional[int] = None
    minutes_tp3: Optional[int] = None

def _fmt_time(minutes_from_now: Optional[int]) -> Optional[str]:
    if minutes_from_now is None: return None
    t = dt.datetime.now(ZoneInfo(TZ)) + dt.timedelta(minutes=minutes_from_now)
    return t.strftime("%Y-%m-%d %H:%M")

def estimate_minutes(distance: Optional[float], per_min_move: Optional[float]) -> Optional[int]:
    if per_min_move is None or per_min_move <= 0 or not distance or distance <= 0:
        return None
    return int(max(1, round(distance / per_min_move)))

def build_eta(tp: TradeProposal, per_min_move: float) -> TradeETA:
    now = dt.datetime.now(ZoneInfo(TZ)).strftime("%Y-%m-%d %H:%M")
    dist_to_sl  = abs(tp.entry - tp.sl)
    dist_to_tp1 = abs(tp.tp1  - tp.entry)
    dist_to_tp2 = abs(tp.tp2  - tp.entry) if tp.tp2 else None
    dist_to_tp3 = abs(tp.tp3  - tp.entry) if tp.tp3 else None
    m_sl  = estimate_minutes(dist_to_sl,  per_min_move)
    m_t1  = estimate_minutes(dist_to_tp1, per_min_move)
    m_t2  = estimate_minutes(dist_to_tp2, per_min_move) if dist_to_tp2 else None
    m_t3  = estimate_minutes(dist_to_tp3, per_min_move) if dist_to_tp3 else None
    return TradeETA(
        now_local=now,
        eta_sl=_fmt_time(m_sl), eta_tp1=_fmt_time(m_t1),
        eta_tp2=_fmt_time(m_t2), eta_tp3=_fmt_time(m_t3),
        minutes_sl=m_sl, minutes_tp1=m_t1, minutes_tp2=m_t2, minutes_tp3=m_t3,
    )

def summarize(tp: TradeProposal, eta: TradeETA, why: str = "") -> str:
    rr = tp.risk_rr()
    rr1_s, rr2_s, rr3_s = f"{rr['rr1']:.2f}", f"{rr['rr2']:.2f}", f"{rr['rr3']:.2f}"

    line_rr = f"RR: TP1 `{rr1_s}`"
    if tp.tp2: line_rr += f" | TP2 `{rr2_s}`"
    if tp.tp3: line_rr += f" | TP3 `{rr3_s}`"

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
        (f"סיבה/תקציר: {why}" if why else "")
    ]
    return "\n".join([p for p in parts if p])






