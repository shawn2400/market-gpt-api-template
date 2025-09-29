# calibration/search.py
from __future__ import annotations
import argparse, json
from pathlib import Path
import pandas as pd
from utils.get_klines import get_klines_sync
from utils.indicators_registry import PARAMS_DIR, run_indicator

def _signals_to_events(sig_list):
    return [(pd.Timestamp(s["ts"]), s["side"]) for s in sig_list]

def _match_score(ref, cand, tol_bars:int=1):
    # התאמה בסיסית; אפשר לשפר בהמשך ל-window לפי אינדקס ברים
    ref_set = {(ts.value, side) for ts, side in ref}
    hits = sum(((ts.value, side) in ref_set) for ts, side in cand)
    precision = hits / max(1, len(cand))
    recall    = hits / max(1, len(ref))
    f1 = 2*precision*recall / max(1e-9, (precision+recall))
    return {"precision": precision, "recall": recall, "f1": f1}

def grid_search_params(df: pd.DataFrame, symbol: str, tf: str, name: str,
                       param_grid: dict, ref_signals: list[dict], tol_bars:int=1) -> dict:
    import itertools
    best = {"score": -1.0}
    ref = _signals_to_events(ref_signals)
    keys = list(param_grid.keys())
    for vals in itertools.product(*[param_grid[k] for k in keys]):
        params = dict(zip(keys, vals))
        out = run_indicator(name, df, symbol=symbol, tf=tf, params=params)
        cand = _signals_to_events(out.get("signals", []))
        m = _match_score(ref, cand, tol_bars=tol_bars)
        if m["f1"] > best["score"]:
            best = {"score": m["f1"], "params": params, "metrics": m}
    PARAMS_DIR.mkdir(parents=True, exist_ok=True)
    (PARAMS_DIR / f"{symbol}_{tf}_{name}.json").write_text(
        json.dumps(best["params"], ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return best

def nightly_recalibrate_from_jobs(jobs_path: str) -> list[dict]:
    p = Path(jobs_path)
    jobs = json.loads(p.read_text(encoding="utf-8"))
    results = []
    for job in jobs:
        symbol = job["symbol"]; tf = job["tf"]; name = job["name"]
        limit  = int(job.get("limit", 800))
        df = get_klines_sync(symbol, interval=tf, limit=limit, market_type=job.get("market", "futures"))
        # ref_signals: ישיר או מקובץ
        ref = job.get("ref_signals", [])
        p_ref = job.get("ref_signals_path")
        if p_ref:
            try:
                ref = json.loads(Path(p_ref).read_text(encoding="utf-8"))
            except Exception:
                pass
        res = grid_search_params(df=df, symbol=symbol, tf=tf, name=name,
                                 param_grid=job["param_grid"], ref_signals=ref, tol_bars=int(job.get("tol_bars", 1)))
        results.append({"symbol": symbol, "tf": tf, "name": name, **res})
    outp = p.with_suffix(".results.json")
    outp.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    return results

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--batch", default=None, help="Path to config/calib_jobs.json (optional if CALIB_JOBS_PATH set)")
    args = ap.parse_args()
    jobs = args.batch or Path.getenv("CALIB_JOBS_PATH") or "config/calib_jobs.json"
    results = nightly_recalibrate_from_jobs(jobs)
    print(json.dumps(results, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
