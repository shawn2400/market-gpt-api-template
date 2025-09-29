# utils/indicators_registry.py
from __future__ import annotations
import importlib, json
from pathlib import Path
from typing import Dict, Any

REGISTRY = {
    "mc_b": "utils.indicators_mc:mc_b",         # 1
    "mc_a": "utils.indicators_mc:mc_a",         # 2
    "alpha": "utils.indicators_alpha:alpha",    # 3 (supertrend/alpha)
    "qqe": "utils.indicators_qqe:qqe",          # 4
    "smc": "utils.indicators_smc:smc",          # 5
    "invictus": "utils.indicators_invictus:invictus",  # 6
    "squeeze": "utils.indicators_extras:squeeze_bb_kc",# 7
    "donchian": "utils.indicators_extras:donchian",     # 8
    "avwap": "utils.indicators_extras:avwap",           # 9
    "chandelier": "utils.indicators_extras:chandelier", # 10
    "vol_regime": "utils.indicators_extras:vol_regime", # 11
    "cvd": "utils.orderflow_cvd:cvd",                   # 12
    "oi": "utils.oi_features:oi_impulse_div",           # 13
    "funding": "utils.funding_bias:funding_bias",       # 14
    "basis": "utils.basis:perp_spot_basis",             # 15
}

PARAMS_DIR = Path("params/optimized")
PARAMS_DIR.mkdir(parents=True, exist_ok=True)

def _load_callable(path: str):
    mod, fn = path.split(":")
    return getattr(importlib.import_module(mod), fn)

def load_params(symbol: str, tf: str, name: str) -> Dict[str, Any] | None:
    p = PARAMS_DIR / f"{symbol}_{tf}_{name}.json"
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return None

def run_indicator(name: str, df, *, symbol: str, tf: str) -> Dict[str, Any]:
    call = _load_callable(REGISTRY[name])
    params = load_params(symbol, tf, name)
    return call.compute(df, tf=tf, params=params) if params else call.compute(df, tf=tf)

def run_all(df, *, symbol: str, tf: str, subset: list[str]|None=None) -> Dict[str, Dict[str,Any]]:
    names = subset or list(REGISTRY.keys())
    out = {}
    for n in names:
        try:
            out[n] = run_indicator(n, df, symbol=symbol, tf=tf)
        except Exception as e:
            out[n] = {"error": str(e)}
    return out
