# calibration/search.py
from __future__ import annotations
import json, itertools
from pathlib import Path
import pandas as pd
import numpy as np
from utils.indicators_registry import run_indicator, PARAMS_DIR

def _signals_to_events(sig_list):
    return [(pd.Timestamp(s["ts"]), s["side"]) for s in sig_list]

def _match_score(ref: list[tuple], cand: list[tuple], tol_bars:int=1) -> dict:
    # ref/cand = [(ts, side)], tol_bars מאפשר ±נר
    if not ref and not cand: return {"overlap":1.0,"precision":1.0,"recall":1.0,"f1":1.0}
    idx_ref = [ts for ts,_ in ref]; idx_cand = [ts for ts,_ in cand]
    hits=0
    for ts, side in cand:
        # מצא ref קרוב בזמן ועם אותו side
        ok=False
        for k,(rts,rside) in enumerate(ref):
            if rside!=side: continue
            if abs((ts - rts).value) <= tol_bars * 10**9 * 60 * 60 * 24:  # fallback אם אינדקס daily; עדיף להמיר ל-bar index
                ok=True; break
        if ok: hits+=1
    precision = hits / max(1,len(cand))
    recall    = hits / max(1,len(ref))
    f1 = 2*precision*recall/max(1e-9,(precision+recall))
    return {"precision":precision,"recall":recall,"f1":f1}

def grid_search_params(df: pd.DataFrame, symbol: str, tf: str, name: str,
                       param_grid: dict[str, list], ref_signals: list[dict], tol_bars:int=1) -> dict:
    best={"score":-1}
    ref = _signals_to_events(ref_signals)
    keys = list(param_grid.keys())
    for vals in itertools.product(*[param_grid[k] for k in keys]):
        params = {k:v for k,v in zip(keys,vals)}
        out = run_indicator(name, df, symbol=symbol, tf=tf, **{"params":params})
        cand = _signals_to_events(out.get("signals",[]))
        m = _match_score(ref, cand, tol_bars=tol_bars)
        score = m["f1"]
        if score > best["score"]:
            best = {"score":score,"params":params,"metrics":m}
    # שמירה
    p = PARAMS_DIR / f"{symbol}_{tf}_{name}.json"
    p.write_text(json.dumps(best["params"], ensure_ascii=False, indent=2), encoding="utf-8")
    return best

def nightly_recalibrate(batch: list[dict]):
    """
    batch: [{"symbol":"BTCUSDT","tf":"15m","name":"qqe","param_grid":{"rsi_len":[10,14,21],"smooth":[3,5,7]}, "ref_signals":[...]}, ...]
    """
    results=[]
    for job in batch:
        r = grid_search_params(
            df=job["df"], symbol=job["symbol"], tf=job["tf"], name=job["name"],
            param_grid=job["param_grid"], ref_signals=job["ref_signals"], tol_bars=1
        )
        results.append({"name":job["name"],"symbol":job["symbol"],"tf":job["tf"],**r})
    return results
