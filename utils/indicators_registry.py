# utils/indicators_registry.py
from __future__ import annotations
import importlib, json, os
from pathlib import Path
from typing import Dict, Any

# ========= Source of Truth =========
REGISTRY = {
    "mc_b":       "utils.indicators_mc:mc_b",               # class mc_b.compute(...)
    "mc_a":       "utils.indicators_mc:mc_a",               # class mc_a.compute(...)
    "alpha":      "utils.indicators_alpha:alpha",           # class alpha.compute(...)
    "qqe":        "utils.indicators_qqe:qqe",               # class qqe.compute(...)
    "smc":        "utils.indicators_smc:smc",               # class smc.compute(...)
    "invictus":   "utils.indicators_invictus:invictus",     # class invictus.compute(...)
    "squeeze":    "utils.indicators_extras:squeeze",        # class squeeze.compute(...)
    "donchian":   "utils.indicators_extras:donchian_c",     # class donchian_c.compute(...)
    "avwap":      "utils.indicators_extras:avwap_c",        # class avwap_c.compute(...)
    "chandelier": "utils.indicators_extras:chandelier_c",   # class chandelier_c.compute(...)
    "vol_regime": "utils.indicators_extras:vol_regime_c",   # class vol_regime_c.compute(...)
    # feeds/IO-backed (async/externals):
    "cvd":        "utils.orderflow_cvd:cvd",                # expects feeds; no HTTP inside indicator
    "oi":         "utils.oi_features:oi_impulse_div",       # expects feeds
    "funding":    "utils.funding_bias:funding_bias",        # async
    "basis":      "utils.basis:perp_spot_basis",            # expects spot/mark feeds
}

PARAMS_DIR = Path(os.getenv("PARAMS_DIR", "params/optimized"))
PARAMS_DIR.mkdir(parents=True, exist_ok=True)

def _load_callable(path: str):
    mod, name = path.split(":")
    obj = getattr(importlib.import_module(mod), name)
    # support both class with .compute and plain function with compute(df,...)
    return obj.compute if hasattr(obj, "compute") else obj

def load_params(symbol: str, tf: str, name: str) -> Dict[str, Any] | None:
    p = PARAMS_DIR / f"{symbol}_{tf}_{name}.json"
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return None
    return None

def run_indicator(name: str, df, *, symbol: str, tf: str, **feeds) -> Dict[str, Any]:
    if name == "funding":
        raise RuntimeError("funding is async; call separately")
    if name not in REGISTRY:
        raise KeyError(f"indicator not found: {name}")
    call = _load_callable(REGISTRY[name])
    params = load_params(symbol, tf, name) or {}
    return call(df, tf=tf, params=params, **feeds)

def run_all(df, *, symbol: str, tf: str, subset: list[str] | None = None, **feeds) -> Dict[str, Dict[str, Any]]:
    names = subset or list(REGISTRY.keys())
    # allow filtering via env (comma-separated)
    env_subset = os.getenv("INDICATORS_SUBSET", "").strip()
    if env_subset:
        names = [n for n in names if n in {x.strip() for x in env_subset.split(",") if x.strip()}]

    out: Dict[str, Dict[str, Any]] = {}
    for n in names:
        if n == "funding":
            continue
        try:
            out[n] = run_indicator(n, df, symbol=symbol, tf=tf, **feeds)
        except Exception as e:
            out[n] = {"error": str(e)}
    return out



