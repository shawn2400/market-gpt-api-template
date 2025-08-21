# utils/anchor.py
from __future__ import annotations
import os, logging, requests
import pandas as pd
from dataclasses import dataclass
from typing import Literal, Tuple, List

Side = Literal["LONG", "SHORT"]
logger = logging.getLogger("algogpt.anchor")

# --- Config ---
FUTURES_BASE = os.getenv("BINANCE_FUTURES_HTTP_BASE", "https://fapi.binance.com")

@dataclass
class AnchorDecision:
    mode_requested: str   # off / soft / hard
    mode_applied: str     # off / soft / hard
    bias: str             # bull / bear / neutral
    score: float          # 0-100
    allow: bool           # האם לאפשר טרייד
    severity: str         # none / weak / strong
    reason: str           # הסבר

def _env_float(key: str, default: float) -> float:
    v = os.getenv(key, "")
    v = v.strip() if isinstance(v, str) else ""
    try:
        return float(v) if v else default
    except Exception:
        return default

def _env_list(key: str, default: str) -> List[str]:
    raw = os.getenv(key, default) or default
    return [x.strip() for x in str(raw).split(",") if str(x).strip()]

def _get_anchor_mode() -> str:
    mode = (os.getenv("BTC_ANCHOR_MODE", "") or "").strip().lower()
    if not mode:
        enforce = (os.getenv("BTC_ANCHOR_ENFORCE", "false") or "").strip().lower() == "true"
        return "hard" if enforce else "soft"
    return mode if mode in {"off", "soft", "hard"} else "soft"

def _fetch_klines(symbol="BTCUSDT", interval="1h", limit=200) -> pd.DataFrame:
    try:
        url = f"{FUTURES_BASE}/fapi/v1/klines"
        r = requests.get(url, params={"symbol": symbol, "interval": interval, "limit": limit}, timeout=8)
        r.raise_for_status()
        arr = r.json()
        if not arr:
            return pd.DataFrame()
        cols = ["open_time","open","high","low","close","volume","close_time","qv","nTrades","taker_base","taker_quote","x"]
        df = pd.DataFrame(arr, columns=cols[:len(arr[0])])
        for c in ("open","high","low","close","volume"):
            df[c] = pd.to_numeric(df[c], errors="coerce")
        return df[["open","high","low","close","volume"]]
    except Exception as e:
        logger.error({"event": "anchor_fetch_error", "error": str(e)})
        return pd.DataFrame()

def _calc_indicators(df: pd.DataFrame) -> Tuple[str, float]:
    if df.empty or len(df) < 50:
        return "neutral", 0.0

    close = df["close"]

    # RSI
    delta = close.diff()
    up = delta.clip(lower=0).rolling(14).mean()
    down = -delta.clip(upper=0).rolling(14).mean()
    rs = up / down.replace(0, 1e-9)
    rsi = 100 - (100 / (1 + rs))
    rsi_val = float(rsi.iloc[-1])

    # EMA
    ema50 = close.ewm(span=50).mean().iloc[-1]
    ema200 = close.ewm(span=200).mean().iloc[-1]

    # Bias
    if rsi_val >= 55 and ema50 > ema200:
        return "bull", min(100.0, rsi_val)
    elif rsi_val <= 45 and ema50 < ema200:
        return "bear", min(100.0, 100 - rsi_val)
    return "neutral", 50.0

def evaluate_anchor(side: Side) -> AnchorDecision:
    mode_req = _get_anchor_mode()
    frames = _env_list("BTC_ANCHOR_FRAMES", "15m,1h")
    strong_th = _env_float("BTC_ANCHOR_STRONG_TH", 70.0)
    weak_th   = _env_float("BTC_ANCHOR_WEAK_TH",   55.0)

    # --- Fetch BTCUSDT candles
    bias, score = "neutral", 0.0
    for tf in frames:
        df = _fetch_klines("BTCUSDT", interval=tf, limit=200)
        b, s = _calc_indicators(df)
        # ניקח הכי "חזק" מבין כל הפריימים
        if b != "neutral" and s > score:
            bias, score = b, s

    conflict = ((side == "LONG" and bias == "bear") or (side == "SHORT" and bias == "bull"))

    if mode_req == "off":
        decision = AnchorDecision("off", "off", bias, score, True, "none", "Anchor disabled")
    elif bias == "neutral" or score <= weak_th:
        decision = AnchorDecision(
            mode_req, mode_req, bias, score, True,
            "none" if bias == "neutral" else "weak",
            f"Anchor {bias} ({score:.1f}) on frames {frames}; no strong conflict"
        )
    elif conflict:
        if score >= strong_th:
            decision = AnchorDecision(
                mode_req, "hard", bias, score, False, "strong",
                f"Strong conflict with BTC anchor ({bias} {score:.1f}≥{strong_th}); HARD block"
            )
        elif mode_req == "hard":
            decision = AnchorDecision(
                "hard", "hard", bias, score, False, "weak",
                f"Conflict with BTC anchor ({bias} {score:.1f}); HARD mode blocks"
            )
        else:
            decision = AnchorDecision(
                "soft", "soft", bias, score, True, "weak",
                f"Conflict with BTC anchor ({bias} {score:.1f}); SOFT mode allows with warning"
            )
    else:
        decision = AnchorDecision(
            mode_req, mode_req, bias, score, True, "none",
            f"Aligned with BTC anchor ({bias} {score:.1f})"
        )

    # ✅ Structured JSON log
    logger.info({
        "event": "anchor_decision",
        "side": side,
        "mode_requested": decision.mode_requested,
        "mode_applied": decision.mode_applied,
        "bias": decision.bias,
        "score": decision.score,
        "allow": decision.allow,
        "severity": decision.severity,
        "reason": decision.reason,
    })
    return decision

__all__ = ["AnchorDecision", "evaluate_anchor"]









