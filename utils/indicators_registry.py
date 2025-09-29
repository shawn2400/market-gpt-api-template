# utils/indicators_registry.py
from __future__ import annotations
import importlib, json
from pathlib import Path
from typing import Dict, Any

REGISTRY = {
    "mc_b":       "utils.indicators_mc:mc_b",
    "mc_a":       "utils.indicators_mc:mc_a",
    "alpha":      "utils.indicators_alpha:alpha",
    "qqe":        "utils.indicators_qqe:qqe",
    "smc":        "utils.indicators_smc:smc",
    "invictus":   "utils.indicators_invictus:invictus",
    "squeeze":    "utils.indicators_extras:squeeze_bb_kc",
    "donchian":   "utils.indicators_extras:donchian",
    "avwap":      "utils.indicators_extras:avwap",
    "chandelier": "utils.indicators_extras:chandelier",
    "vol_regime": "utils.indicators_extras:vol_regime",
    "cvd":        "utils.orderflow_cvd:cvd",
    "oi":         "utils.oi_features:oi_impulse_div",
    "funding":    "utils.funding_bias:funding_bias",      # async
    "basis":      "utils.basis:perp_spot_basis",
}

PARAMS_DIR = Path("params/optimized"); PARAMS_DIR.mkdir(parents=True, exist_ok=True)

def _load_callable(path: str):
    mod, fn = path.split(":")
    return getattr(importlib.import_module(mod), fn)

def load_params(symbol: str, tf: str, name: str) -> Dict[str, Any] | None:
    p = PARAMS_DIR / f"{symbol}_{tf}_{name}.json"
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return None

def run_indicator(name: str, df, *, symbol: str, tf: str, **feeds) -> Dict[str, Any]:
    call = _load_callable(REGISTRY[name])
    params = load_params(symbol, tf, name)
    # funding הוא async – אל תקרא כאן (טפל בו ב-fuser/scheduler)
    if name == "funding":
        raise RuntimeError("funding is async; call separately")
    return call.compute(df, tf=tf, params=params or {}, **feeds)

def run_all(df, *, symbol: str, tf: str, subset: list[str] | None = None, **feeds) -> Dict[str, Dict[str,Any]]:
    names = subset or list(REGISTRY.keys())
    out = {}
    for n in names:
        if n == "funding":  # דלג – לטפל בנפרד
            continue
        try:
            out[n] = run_indicator(n, df, symbol=symbol, tf=tf, **feeds)
        except Exception as e:
            out[n] = {"error": str(e)}
    return out

