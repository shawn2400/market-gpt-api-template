# utils/btc_anchor.py
from __future__ import annotations
import os, requests
import pandas as pd
from dataclasses import dataclass
from typing import Literal, List

Side = Literal["LONG", "SHORT"]

@dataclass
class AnchorDecision:
    mode_requested: str   # off / soft / hard
    mode_applied: str     # off / soft / hard
    bias: str             # bull / bear / neutral
    score: float          # 0-100
    allow: bool           # האם לאפשר טרייד
    severity: str         # none / weak / strong
    reason: str           # הסבר

FUTURES_BASE = os.getenv("BINANCE_FUTURES_HTTP_BASE", "https://fapi.binance.com")

# --- אינדיקטורים ---
def rsi(series: pd.Series, period: int = 14) -> float:
    delta = series.diff()
    gain = delta.where(delta > 0, 0.0).rolling(period).mean()
    loss = -delta.where(delta < 0, 0.0).rolling(period).mean()
    rs = gain / (loss + 1e-9)
    return float(100 - (100 / (1 + rs.iloc[-1])))

def ema(series: pd.Series, span: int) -> float:
    return float(series.ewm(span=span).mean().iloc[-1])

def adx(df: pd.DataFrame, period: int = 14) -> float:
    high, low, close = df["high"], df["low"], df["close"]
    plus_dm = (high.diff().clip(lower=0)).fillna(0)
    minus_dm = (-low.diff().clip(upper=0)).fillna(0)
    tr = (high.combine(close.shift(), max) - low.combine(close.shift(), min)).fillna(0)
    atr = tr.rolling(period).mean()
    plus_di = 100 * (plus_dm.rolling(period).mean() / atr)
    minus_di = 100 * (minus_dm.rolling(period).mean() / atr)
    dx = (100 * (plus_di - minus_di).abs() / (plus_di + minus_di)).fillna(0)
    return float(dx.rolling(period).mean().iloc[-1])

# --- Fetch ---
def fetch_klines(symbol: str, interval: str, limit: int = 200) -> pd.DataFrame:
    url = f"{FUTURES_BASE}/fapi/v1/klines"
    r = requests.get(url, params={"symbol": symbol, "interval": interval, "limit": limit}, timeout=10)
    r.raise_for_status()
    arr = r.json()
    if not arr:
        return pd.DataFrame()
    cols = ["open_time","open","high","low","close","volume","close_time",
            "qv","nTrades","taker_base","taker_quote","x"]
    df = pd.DataFrame(arr, columns=cols[:len(arr[0])])
    for c in ("open","high","low","close"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df[["open","high","low","close"]]

# --- Evaluate BTC Anchor ---
def evaluate_anchor(side: Side) -> AnchorDecision:
    frames = (os.getenv("BTC_ANCHOR_FRAMES", "15m,1h,4h").split(","))
    mode_req = (os.getenv("BTC_ANCHOR_MODE", "soft")).lower()
    strong_th = float(os.getenv("BTC_ANCHOR_STRONG_TH", 70))
    weak_th   = float(os.getenv("BTC_ANCHOR_WEAK_TH", 55))

    votes = []
    for tf in frames:
        try:
            df = fetch_klines("BTCUSDT", tf, limit=200)
            if df.empty: 
                continue
            r = rsi(df["close"])
            e21 = ema(df["close"], 21)
            e50 = ema(df["close"], 50)
            adx_val = adx(df)

            bias = "bull" if (r > 55 and e21 > e50) else "bear" if (r < 45 and e21 < e50) else "neutral"
            score = 60 if bias != "neutral" else 50
            if adx_val > 25:
                score += 15
            votes.append((bias, score))
        except Exception:
            continue

    if not votes:
        return AnchorDecision(mode_req, mode_req, "neutral", 0.0, True, "none", "no BTC data")

    bull_votes = sum(1 for b, _ in votes if b == "bull")
    bear_votes = sum(1 for b, _ in votes if b == "bear")
    bias = "bull" if bull_votes > bear_votes else "bear" if bear_votes > bull_votes else "neutral"
    score = sum(s for _, s in votes) / len(votes)

    conflict = ((side == "LONG" and bias == "bear") or (side == "SHORT" and bias == "bull"))

    if mode_req == "off":
        return AnchorDecision("off", "off", bias, score, True, "none", "Anchor disabled")

    if conflict and score >= strong_th:
        return AnchorDecision(mode_req, "hard", bias, score, False, "strong", f"Strong {bias} anchor ({score:.1f}) blocks")
    if conflict and mode_req == "hard":
        return AnchorDecision("hard", "hard", bias, score, False, "weak", f"Conflict {bias} anchor ({score:.1f}) - hard block")
    if conflict:
        return AnchorDecision("soft", "soft", bias, score, True, "weak", f"Conflict {bias} anchor ({score:.1f}) - soft allow")

    return AnchorDecision(mode_req, mode_req, bias, score, True, "none", f"Aligned BTC anchor {bias} ({score:.1f})")







