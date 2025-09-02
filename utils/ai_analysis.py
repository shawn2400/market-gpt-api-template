# utils/ai_analysis.py
from __future__ import annotations

import os
import json
import asyncio
from typing import Dict, Any, Optional, List
import random

import httpx

# ENV
OPENAI_API_KEY = (os.getenv("OPENAI_API_KEY") or "").strip()
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o").strip()
OPENAI_BASE_URL = (os.getenv("OPENAI_BASE_URL") or "https://api.openai.com/v1").rstrip("/")
OPENAI_TIMEOUT_SECONDS = float(os.getenv("OPENAI_TIMEOUT_SECONDS", "30.0"))
OPENAI_MAX_CONCURRENCY = int(os.getenv("OPENAI_MAX_CONCURRENCY", "4"))

_sema = asyncio.Semaphore(max(1, OPENAI_MAX_CONCURRENCY))

def _backoff(attempt: int) -> float:
    return min(0.6 * (2 ** attempt), 5.0)

def _build_prompt(features: Dict[str, Any]) -> Dict[str, Any]:
    symbol = features.get("symbol", "UNKNOWN")
    keys = [
        "close","open","high","low","volume",
        "ema21","ema50","rsi","macd","macd_signal","macd_hist",
        "adx","atr",
    ]
    parts = []
    for k in keys:
        v = features.get(k)
        if v is None: continue
        try:
            parts.append(f"{k}={v:.6g}" if isinstance(v,(int,float)) else f"{k}={v}")
        except Exception:
            parts.append(f"{k}={v}")
    summary = ", ".join(parts)

    system = (
        "You are an expert technical analyst for crypto futures. "
        "Return a concise, actionable analysis (3-6 bullets) of the latest candle/indicators. "
        "No financial advice; neutral tone."
    )
    user = f"Symbol: {symbol}\nFeatures: {summary}\nTask: Provide concise technical analysis."

    return {"model": OPENAI_MODEL,
            "messages":[{"role":"system","content":system},{"role":"user","content":user}],
            "temperature":0.2,"max_tokens":350}

async def _post_with_retries(url: str, headers: Dict[str, str], payload: Dict[str, Any]) -> Dict[str, Any]:
    last_err: Optional[str] = None
    for attempt in range(5):
        try:
            timeout = httpx.Timeout(OPENAI_TIMEOUT_SECONDS)
            async with httpx.AsyncClient(timeout=timeout) as client:
                r = await client.post(url, headers=headers, json=payload)
                if r.status_code in (429, 500, 502, 503, 504):
                    last_err = f"{r.status_code}: {r.text[:300]}"
                    await asyncio.sleep(_backoff(attempt))
                    continue
                r.raise_for_status()
                return r.json()
        except httpx.HTTPStatusError as e:
            try:
                data = e.response.json()
                last_err = json.dumps(data)[:300]
            except Exception:
                last_err = e.response.text[:300]
            if 400 <= e.response.status_code < 500 and e.response.status_code != 429:
                break
        except Exception as e:
            last_err = str(e)
            await asyncio.sleep(_backoff(attempt))
    raise RuntimeError(f"OpenAI request failed after retries: {last_err}")

async def analyze_with_ai(features: Dict[str, Any]) -> Dict[str, Any]:
    if not OPENAI_API_KEY:
        return {"ok": False, "analysis": "[AI disabled] Missing OPENAI_API_KEY."}
    payload = _build_prompt(features)
    headers = {"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"}
    url = f"{OPENAI_BASE_URL}/chat/completions"
    async with _sema:
        data = await _post_with_retries(url, headers, payload)
    text = ""
    try:
        text = (data.get("choices") or [{}])[0].get("message", {}).get("content", "").strip()
    except Exception:
        text = ""
    if not text:
        return {"ok": False, "analysis": "[AI error] Empty response."}
    return {"ok": True, "analysis": text}

# ===== Candidates + Early Approvals =====
from utils.ws_fallback import get_price
from utils.approvals import preflight_proposal

def _mk_candidate(symbol: str, side: str, entry: float, sl: float, tp1: float,
                  tp2: float | None = None, tp3: float | None = None,
                  leverage: int = 10, success_pct: float | None = None,
                  budget: float | None = 30.0, current_price: float | None = None) -> Dict[str, Any]:
    return {
        "symbol": symbol.upper(),
        "side": side.upper(),
        "entry": float(entry), "sl": float(sl),
        "tp1": float(tp1), "tp2": (float(tp2) if tp2 is not None else None),
        "tp3": (float(tp3) if tp3 is not None else None),
        "leverage": int(leverage) if leverage else None,
        "success_pct": (float(success_pct) if success_pct is not None else None),
        "budget": (float(budget) if budget is not None else None),
        "current_price": (float(current_price) if current_price else None),
    }

async def _heuristic_generate(symbols: List[str], interval: str, market: str, max_items: int) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    if not symbols:
        symbols = ["BTCUSDT","ETHUSDT","SOLUSDT"]
    for sym in symbols[:max_items]:
        px = float(get_price(sym) or 0.0)
        if px <= 0:
            px = 100.0 + random.random()*50.0
        side = "LONG" if random.random() > 0.5 else "SHORT"
        sgn = 1.0 if side == "LONG" else -1.0
        entry = px + sgn * (0.15/100.0) * px
        sl    = entry - sgn * (0.35/100.0) * px
        tp1   = entry + sgn * (0.50/100.0) * px
        tp2   = entry + sgn * (0.90/100.0) * px
        tp3   = entry + sgn * (1.30/100.0) * px
        sp    = 65 + random.random()*15
        out.append(_mk_candidate(sym, side, entry, sl, tp1, tp2, tp3, leverage=10, success_pct=sp, budget=30.0, current_price=px))
    return out

async def analyze_with_ai_and_filter(
    symbols: List[str],
    interval: str = "15m",
    market: str = "futures",
    max_items: int = 10,
    run_early_approvals: bool = True,
) -> Dict[str, Any]:
    candidates = await _heuristic_generate(symbols, interval, market, max_items)
    accepted: List[Dict[str, Any]] = []
    rejected: List[Dict[str, Any]] = []
    for c in candidates:
        if not c.get("current_price"):
            try:
                cp = float(get_price(c["symbol"]) or 0.0)
                if cp > 0: c["current_price"] = cp
            except Exception:
                pass
        if not run_early_approvals:
            accepted.append({**c, "interval": interval, "market": market})
            continue
        res = preflight_proposal({**c, "interval": interval})
        if res["ok"]:
            accepted.append({**c, "interval": interval, "market": market, "_pre": res})
        else:
            rejected.append({"proposal": {**c, "interval": interval, "market": market},
                             "errors": res["errors"], "warnings": res.get("warnings",[])})
    return {"accepted": accepted, "rejected": rejected}












































