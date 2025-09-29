from __future__ import annotations
import argparse, json, sys
from pathlib import Path
import pandas as pd
from utils.get_klines import get_klines_sync
from utils.indicators_registry import PARAMS_DIR, run_indicator

# --- פונקציות core שהצגתי קודם (grid_search_params, nightly_recalibrate) ---

def _signals_to_events(sig_list):
    import pandas as pd
    return [(pd.Timestamp(s["ts"]), s["side"]) for s in sig_list]

def _match_score(ref, cand, tol_bars:int=1):
    # גרסה פשוטה – מספיק לכיול ראשוני
    hits=0
    ref_set = {(ts.value, side) for ts,side in ref}
    for ts,side in cand:
        key=(ts.value, side)
        if key in ref_set:
            hits+=1
    precision = hits / max(1,len(cand)); recall = hits / max(1,len(ref))
    f1 = 2*precision*recall/max(1e-9,(precision+recall))
    return {"precision":precision,"recall":recall,"f1":f1}

def grid_search_params(df: pd.DataFrame, symbol: str, tf: str, name: str,
                       param_grid: dict, ref_signals: list[dict], tol_bars:int=1) -> dict:
    import itertools, json
    best={"score":-1}
    ref = _signals_to_events(ref_signals)
    keys = list(param_grid.keys())
    for vals in itertools.product(*[param_grid[k] for k in keys]):
        params = {k:v for k,v in zip(keys,vals)}
        out = run_indicator(name, df, symbol=symbol, tf=tf, params=params)
        cand = _signals_to_events(out.get("signals",[]))
        m = _match_score(ref, cand, tol_bars=tol_bars)
        score = m["f1"]
        if score > best["score"]:
            best = {"score":score,"params":params,"metrics":m}
    p = PARAMS_DIR / f"{symbol}_{tf}_{name}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(best["params"], ensure_ascii=False, indent=2), encoding="utf-8")
    return best

def nightly_recalibrate_from_jobs(jobs_path: str) -> list[dict]:
    p = Path(jobs_path); jobs = json.loads(p.read_text(encoding="utf-8"))
    results=[]
    for job in jobs:
        symbol = job["symbol"]; tf = job["tf"]; name = job["name"]
        limit  = int(job.get("limit", 800))
        df = get_klines_sync(symbol, interval=tf, limit=limit, market_type=job.get("market","futures"))
        ref = job.get("ref_signals", [])
        res = grid_search_params(df=df, symbol=symbol, tf=tf, name=name,
                                 param_grid=job["param_grid"], ref_signals=ref, tol_bars=int(job.get("tol_bars",1)))
        results.append({"symbol":symbol,"tf":tf,"name":name, **res})
    outp = p.with_suffix(".results.json")
    outp.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    return results

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--batch", required=True, help="Path to config/calib_jobs.json")
    args = ap.parse_args()
    results = nightly_recalibrate_from_jobs(args.batch)
    print(json.dumps(results, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
