# calibration/search.py
from __future__ import annotations
import argparse, json, os, time, itertools
from pathlib import Path
import pandas as pd
from utils.get_klines import get_klines_sync
from utils.indicators_registry import PARAMS_DIR, run_indicator

# ---------------- base helpers ----------------
def _signals_to_events(sig_list):
    return [(pd.Timestamp(s["ts"]), s["side"]) for s in sig_list]

def _match_score(ref, cand, tol_bars:int=1):
    # התאמה בסיסית; אפשר לשפר בהמשך לחלון טולרנס על ציר ברים
    ref_set = {(ts.value, side) for ts, side in ref}
    hits = 0
    for ts, side in cand:
        if (ts.value, side) in ref_set:
            hits += 1
    precision = hits / max(1, len(cand))
    recall    = hits / max(1, len(ref))
    f1 = 2*precision*recall / max(1e-9, (precision+recall))
    return {"precision": precision, "recall": recall, "f1": f1}

def _iter_param_combos(param_grid: dict) -> list[dict]:
    if not param_grid:
        return [{}]
    keys = list(param_grid.keys())
    vals = [param_grid[k] for k in keys]
    combos = []
    for prod in itertools.product(*vals):
        combos.append({k:v for k,v in zip(keys, prod)})
    return combos

def _sample_combos(combos: list[dict], k: int, seed: int) -> list[dict]:
    # דגימה דטרמיניסטית (לשחזור) + ערבוב קל
    import random
    if k <= 0 or k >= len(combos):
        return combos
    rnd = random.Random(int(seed))
    combos_sorted = sorted(combos, key=lambda c: hash(tuple(sorted(c.items()))))
    return rnd.sample(combos_sorted, k)

def _auto_cap_from_refs(ref_count: int, tf: str, base_cap: int) -> int:
    # פחות רפרנסים => פחות קומבינציות; TF גבוה => אפשר מעט יותר
    if ref_count < 8:   return min(base_cap, 40)
    if ref_count < 15:  return min(base_cap, 80)
    if tf in ("1h","2h","4h"):
        return min(base_cap, max(100, base_cap))  # השאר קאפ מלא
    return base_cap

# ---------------- grid search with throttling ----------------
def grid_search_params(df: pd.DataFrame, symbol: str, tf: str, name: str,
                       param_grid: dict, ref_signals: list[dict], tol_bars:int=1,
                       max_combos:int|None=None, random_seed:int=1337,
                       time_budget_sec: float|None = None,
                       ref_count_hint: int|None = None) -> dict:
    """
    מחפש את הפרמטרים הטובים ביותר לפי F1 מול ref_signals, עם:
      - הגבלת מקס’ קומבינציות (דגימה דטרמיניסטית)
      - תקציב זמן אופציונלי (יעצור בנימוס)
      - קאפ אוטומטי לפי ref_count/TF אם max_combos לא סופק
    """
    best = {"score": -1.0}
    ref = _signals_to_events(ref_signals)
    combos = _iter_param_combos(param_grid)

    # קאפ אוטומטי אם לא נשלח, לפי כמות ref ו-TF
    if not max_combos or max_combos <= 0:
        cap_env = int(os.getenv("CALIB_MAX_COMBOS_PER_JOB", "120"))
        max_combos = _auto_cap_from_refs(ref_count_hint or len(ref), tf, cap_env)

    combos = _sample_combos(combos, k=min(max_combos, len(combos)), seed=random_seed)

    t0 = time.time()
    for params in combos:
        out = run_indicator(name, df, symbol=symbol, tf=tf, params=params)
        cand = _signals_to_events(out.get("signals", []))
        m = _match_score(ref, cand, tol_bars=tol_bars)
        if m["f1"] > best["score"]:
            best = {"score": m["f1"], "params": params, "metrics": m}
        # תקציב זמן—עצור בנימוס אם חרג
        if time_budget_sec and (time.time() - t0) > float(time_budget_sec):
            break

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

        ref = job.get("ref_signals", [])
        p_ref = job.get("ref_signals_path")
        if p_ref:
            try:
                ref = json.loads(Path(p_ref).read_text(encoding="utf-8"))
            except Exception:
                pass

        res = grid_search_params(
            df=df, symbol=symbol, tf=tf, name=name,
            param_grid=job.get("param_grid", {}),
            ref_signals=ref, tol_bars=int(job.get("tol_bars", 1)),
            max_combos=int(job.get("max_combos", 0)) or None,
            random_seed=int(job.get("random_seed", int(os.getenv("CALIB_RANDOM_SEED","1337")))),
            time_budget_sec=job.get("time_budget_sec"),
            ref_count_hint=len(ref),
        )
        results.append({"symbol": symbol, "tf": tf, "name": name, **res})
    outp = p.with_suffix(".results.json")
    outp.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    return results

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--batch", default=None, help="Path to config/calib_jobs.json (optional if CALIB_JOBS_PATH set)")
    args = ap.parse_args()
    jobs = args.batch or os.getenv("CALIB_JOBS_PATH") or "config/calib_jobs.json"
    results = nightly_recalibrate_from_jobs(jobs)
    print(json.dumps(results, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()

