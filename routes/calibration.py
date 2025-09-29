# routes/calibration.py  (LIVE)
from __future__ import annotations
import os, json, time
from pathlib import Path
from typing import Optional, Dict, Any, List, Iterable
from fastapi import APIRouter, Depends, Body, HTTPException

# --- Auth (כמו בפרויקט) ---
try:
    from utils.auth import require_api_key
except Exception:
    def require_api_key():
        return True

from calibration.search import nightly_recalibrate_from_jobs
from utils.indicators_registry import PARAMS_DIR

router = APIRouter(prefix="/calib", tags=["calibration"], dependencies=[Depends(require_api_key)])

# -------------------- Helpers --------------------
def _calib_enabled(force: bool = False) -> bool:
    return True if force else (os.getenv("CALIB_ENABLE","0").lower() in ("1","true","yes","on"))

def _env_csv(name: str, default: str = "") -> List[str]:
    return [x.strip() for x in (os.getenv(name, default) or "").split(",") if x.strip()]

def _jobs_default_path() -> str:
    return os.getenv("CALIB_JOBS_PATH", "config/calib_jobs.json")

def _watchlist() -> List[str]:
    wl = _env_csv("WATCHLIST", "BTCUSDT,ETHUSDT")
    return [w.upper() for w in wl]

def _tfs() -> List[str]:
    return _env_csv("INDICATOR_INTERVALS", "15m,1h")

def _load_trades_log(path: str) -> List[Dict[str, Any]]:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"trades_log not found: {p}")
    raw = json.loads(p.read_text(encoding="utf-8"))
    if isinstance(raw, list):
        return raw
    if isinstance(raw, dict):
        for k in ("rows","data","items"):
            if isinstance(raw.get(k), list):
                return raw[k]
    raise ValueError("Unsupported trades_log format")

def _normalize_side(side: str) -> Optional[str]:
    s = (side or "").lower()
    if s in ("long","buy","open_long","tp_long","tp1_long","entry_long"): return "long"
    if s in ("short","sell","open_short","tp_short","tp1_short","entry_short"): return "short"
    return None

def _iso_ts(val) -> Optional[str]:
    from datetime import datetime, timezone
    if val is None: return None
    if isinstance(val, (int, float)):
        try:
            return datetime.fromtimestamp(float(val)/1000.0, tz=timezone.utc).isoformat()
        except Exception:
            return None
    s = str(val)
    try:
        return datetime.fromisoformat(s.replace("Z","+00:00")).astimezone(timezone.utc).isoformat()
    except Exception:
        try:
            f = float(s)
            return datetime.fromtimestamp(f, tz=timezone.utc).isoformat()
        except Exception:
            return None

def _extract_ref_by_symbol_tf(rows: List[Dict[str, Any]],
                              symbols: Iterable[str],
                              tfs: Iterable[str]) -> Dict[str, List[Dict[str, Any]]]:
    out: Dict[str, List[Dict[str, Any]]] = {}
    syms = {s.upper() for s in symbols}
    tfs_set = {t for t in tfs}
    for r in rows:
        sym = (r.get("symbol") or r.get("sym") or r.get("pair") or "").upper()
        tf  =  (r.get("tf") or r.get("timeframe") or r.get("interval") or "").lower()
        if (sym in syms) and (tf in tfs_set):
            ts = _iso_ts(r.get("ts") or r.get("close_time") or r.get("time"))
            side = _normalize_side(r.get("side") or r.get("action") or r.get("dir"))
            if ts and side in ("long","short"):
                key = f"{sym}_{tf}"
                out.setdefault(key, []).append({"ts": ts, "side": side})
    return out

def _write_json(path: str, obj: Any) -> None:
    p = Path(path); p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")

# -------------------- Grid presets + Auto mode --------------------
# מוד “אוטומטי” יהיה דיפולט: CALIB_GRID_MODE=auto (או plus/pro/lite)
CALIB_GRID_MODE_DEFAULT = os.getenv("CALIB_GRID_MODE", "auto").strip().lower()

GRID_LITE = {
    "mc_b":       {"rsi_len": [14, 21], "vwma_len": [20, 30]},
    "mc_a":       {"wave_len": [9, 12], "signal_len": [4, 6]},
    "alpha":      {"atr_mult": [1.2, 1.6], "atr_len": [10, 14]},
    "qqe":        {"len": [14, 21], "factor": [3.0, 4.0]},
    "smc":        {"swing_len": [3, 5], "ob_len": [10, 20], "fvg_len": [10, 20]},
    "invictus":   {"w_momo": [0.8, 1.0], "w_vol": [0.8, 1.0], "threshold": [0.6, 0.7]},
    "squeeze":    {"bb_len": [20], "bb_mult": [2.0], "kc_len": [20], "kc_mult": [1.5, 2.0]},
    "donchian":   {"len": [20, 30]},
    "avwap":      {"anchor": ["session", "week"]},
    "chandelier": {"atr_len": [14, 22], "atr_mult": [2.5, 3.0]},
    "vol_regime": {"window": [50, 100], "method": ["stdev", "kde"]},
    "cvd":        {"smooth": [5, 13]},
    "oi":         {"window": [20, 50], "z_thresh": [1.5, 2.0]},
    "basis":      {"window": [10, 20], "z_thresh": [1.0, 1.5]},
}

GRID_PLUS = {
    "mc_b":       {"rsi_len": [12,14,18,21,24], "vwma_len": [20,24,30,36]},
    "mc_a":       {"wave_len": [9,10,12,14], "signal_len": [3,4,6,8]},
    "alpha":      {"atr_mult": [1.1,1.3,1.6,1.9], "atr_len": [7,10,14,21]},
    "qqe":        {"len": [10,14,21,28], "factor": [2.5,3.0,3.5,4.0]},
    "smc":        {"swing_len": [3,5,7], "ob_len": [10,20,30], "fvg_len": [10,20,30]},
    "invictus":   {"w_momo": [0.6,0.8,1.0], "w_vol": [0.6,0.8,1.0], "threshold": [0.55,0.6,0.7,0.75]},
    "squeeze":    {"bb_len": [20,22], "bb_mult": [1.8,2.0,2.2], "kc_len": [20,24], "kc_mult": [1.5,1.8,2.0]},
    "donchian":   {"len": [20,24,30,36]},
    "avwap":      {"anchor": ["session","week","month"]},
    "chandelier": {"atr_len": [14,18,22,26], "atr_mult": [2.0,2.5,3.0,3.5]},
    "vol_regime": {"window": [50,75,100,150], "method": ["stdev", "kde"]},
    "cvd":        {"smooth": [5,8,13,21]},
    "oi":         {"window": [20,34,50,89], "z_thresh": [1.2,1.5,2.0]},
    "basis":      {"window": [10,14,20,30], "z_thresh": [0.8,1.0,1.3,1.6]},
}

GRID_PRO = {
    "mc_b":       {"rsi_len": [10,12,14,18,21,24,28], "vwma_len": [16,20,24,30,36,44]},
    "mc_a":       {"wave_len": [8,9,10,12,14,16], "signal_len": [3,4,5,6,8,10]},
    "alpha":      {"atr_mult": [1.0,1.2,1.4,1.6,1.8,2.0], "atr_len": [7,10,14,21,28]},
    "qqe":        {"len": [10,12,14,21,28,34], "factor": [2.0,2.5,3.0,3.5,4.0]},
    "smc":        {"swing_len": [3,5,7,9], "ob_len": [10,20,30,40], "fvg_len": [10,20,30,40]},
    "invictus":   {"w_momo": [0.5,0.6,0.8,1.0], "w_vol": [0.5,0.6,0.8,1.0], "threshold": [0.5,0.55,0.6,0.65,0.7,0.75]},
    "squeeze":    {"bb_len": [18,20,22,26], "bb_mult": [1.6,1.8,2.0,2.2], "kc_len": [18,20,24,28], "kc_mult": [1.4,1.6,1.8,2.0]},
    "donchian":   {"len": [18,20,24,30,36,48]},
    "avwap":      {"anchor": ["session","week","month","ytd"]},
    "chandelier": {"atr_len": [10,14,18,22,26,30], "atr_mult": [2.0,2.3,2.5,3.0,3.3,3.5]},
    "vol_regime": {"window": [34,50,75,100,150,200], "method": ["stdev", "kde"]},
    "cvd":        {"smooth": [5,8,13,21,34]},
    "oi":         {"window": [20,34,50,89,144], "z_thresh": [1.0,1.2,1.5,2.0]},
    "basis":      {"window": [10,14,20,30,40], "z_thresh": [0.7,0.9,1.1,1.3,1.6]},
}

def _pick_mode_auto(tf: str, ref_count: int) -> str:
    # מעט דוגמאות => lite; בינוני => plus; גדול + TF גבוה => pro
    if ref_count < 8:   return "lite"
    if ref_count < 20:  return "plus"
    if tf in ("1h","2h","4h"): return "pro"
    return "plus"

def _grid_for_mode(name: str, mode: str) -> dict:
    base = GRID_LITE
    if mode == "plus": base = GRID_PLUS
    elif mode == "pro": base = GRID_PRO
    return base.get(name, {})

# -------------------- Schemas (Pydantic-free) --------------------
class BuildJobsRequest(Dict[str, Any]):  # FastAPI יקבל dict
    pass

class RunLiveRequestModel:
    pass

# -------------------- Routes --------------------
@router.get("/ping")
def calib_ping():
    return {
        "ok": True,
        "enabled": _calib_enabled(),
        "params_dir": str(PARAMS_DIR),
        "jobs_default": _jobs_default_path(),
        "watchlist": _watchlist(),
        "tfs": _tfs(),
        "grid_mode_default": CALIB_GRID_MODE_DEFAULT,
    }

@router.get("/status")
def calib_status():
    items = []
    if PARAMS_DIR.exists():
        for p in sorted(PARAMS_DIR.glob("*.json")):
            try:
                st = p.stat()
                items.append({"file": p.name, "size": st.st_size, "mtime": int(st.st_mtime)})
            except Exception:
                items.append({"file": p.name})
    jobs_path = _jobs_default_path()
    return {"ok": True, "count": len(items), "items": items, "jobs_path": jobs_path, "jobs_exists": Path(jobs_path).exists()}

@router.post("/build-jobs")
def build_jobs(req: Dict[str, Any] = Body(default={})):
    """
    בונה config/calib_jobs.json אמיתי מתוך trades_log LIVE.

    Body (אופציונלי):
      - trades_log_path: ברירת מחדל 'data/trades_log.json'
      - indicators: ['mc_b','alpha','qqe', ...] או "all"
      - param_grids: {name: {param: [values...]}} (דריסה ידנית)
      - tol_bars: ברירת מחדל 1
      - limit: ברירת מחדל 800 (מספר נרות לטעינה לכיול)
      - market: ברירת מחדל DEFAULT_MARKET
      - grid_mode: 'auto' (דיפולט)/'lite'/'plus'/'pro'
      - max_combos_per_job: דיפולט מה-ENV (CALIB_MAX_COMBOS_PER_JOB, 120)
      - random_seed: דיפולט 1337
      - time_budget_sec: רמז לזמן ריצה מקס' לכל job (אופציונלי)
    """
    trades_log_path = req.get("trades_log_path") or "data/trades_log.json"
    grid_mode_req = (req.get("grid_mode") or CALIB_GRID_MODE_DEFAULT or "auto").strip().lower()
    tol_bars = int(req.get("tol_bars", 1))
    limit = int(req.get("limit", 800))
    market = req.get("market", os.getenv("DEFAULT_MARKET","futures"))

    max_combos_per_job = int(req.get("max_combos_per_job", int(os.getenv("CALIB_MAX_COMBOS_PER_JOB","120"))))
    random_seed = int(req.get("random_seed", int(os.getenv("CALIB_RANDOM_SEED","1337"))))
    time_budget_sec = req.get("time_budget_sec")  # יכול להיות None

    # בחירת אינדיקטורים
    ALL_INDI = ["mc_b","mc_a","alpha","qqe","smc","invictus","squeeze","donchian","avwap","chandelier","vol_regime","cvd","oi","basis"]
    indicators_req = req.get("indicators")
    if not indicators_req:
        indicators = ["mc_b","alpha","qqe","smc","invictus","chandelier","squeeze"]  # ברירת מחדל טובה
    elif indicators_req == "all":
        indicators = ALL_INDI
    else:
        indicators = [x for x in indicators_req if x in set(ALL_INDI)]

    # טעינת רפרנסים
    rows = _load_trades_log(trades_log_path)
    ref_by_key = _extract_ref_by_symbol_tf(rows, _watchlist(), _tfs())

    # פרמטרי דיפולט לגרידים (אפשר דריסה per-name)
    user_grids: Dict[str, Dict[str, List[Any]]] = (req.get("param_grids") or {})

    # כתיבת קבצי ref_signals לכל צמד/TF
    ref_files: Dict[str, str] = {}
    for key, arr in ref_by_key.items():
        dst = f"data/ref_signals_{key.lower()}.json"
        _write_json(dst, arr)
        ref_files[key] = dst

    # יצירת jobs list עם מצב גריד (auto לפי ref_count/TF אם צריך)
    jobs = []
    chosen_modes: Dict[str, str] = {}
    for key in sorted(ref_by_key.keys()):
        sym, tf = key.split("_", 1)
        ref_count = len(ref_by_key[key])

        mode = grid_mode_req
        if mode == "auto":
            mode = _pick_mode_auto(tf, ref_count)
        chosen_modes[key] = mode

        for name in indicators:
            # דריסה ידנית אם ניתנה; אחרת מה-Mode
            grid = user_grids.get(name)
            if grid is None:
                grid = _grid_for_mode(name, mode)

            # ref_signals ישירות – כדי לא לדרוש I/O נוסף בזמן ריצה
            try:
                ref = json.loads(Path(ref_files[key]).read_text(encoding="utf-8"))
            except Exception:
                ref = []

            jobs.append({
                "symbol": sym,
                "tf": tf,
                "name": name,
                "param_grid": grid or {},
                "ref_signals": ref,
                "tol_bars": tol_bars,
                "limit": limit,
                "market": market,
                # עומס/דגימה/תקציב זמן
                "max_combos": max_combos_per_job,
                "random_seed": random_seed,
                "time_budget_sec": time_budget_sec,
                "grid_mode_effective": mode,
            })

    jobs_path = _jobs_default_path()
    _write_json(jobs_path, jobs)
    return {
        "ok": True,
        "jobs_path": jobs_path,
        "jobs_count": len(jobs),
        "refs_written": list(ref_files.values()),
        "grid_mode_default": CALIB_GRID_MODE_DEFAULT,
        "grid_mode_effective_by_key": chosen_modes,
        "indicators": indicators,
        "max_combos_per_job": max_combos_per_job,
    }

@router.post("/run-live")
def run_live(req: Dict[str, Any] = Body(default={})):
    """
    זרימה מלאה בלייב:
      אם חסר calib_jobs.json — יבנה אותו מיידית מ-trades_log.json, ואז יריץ כיול.

    Body (אופציונלי – כמו build-jobs):
      trades_log_path / indicators / param_grids / tol_bars / limit / market / jobs_path
      grid_mode / max_combos_per_job / random_seed / time_budget_sec
      force_enable=true כדי לעקוף CALIB_ENABLE
    """
    if not _calib_enabled(req.get("force_enable", False)):
        return {"ok": False, "error": "calibration_disabled", "hint": "Set CALIB_ENABLE=1 or use force_enable"}

    jobs_path = req.get("jobs_path") or _jobs_default_path()
    if not Path(jobs_path).exists():
        build_res = build_jobs(req)
        if not build_res.get("ok"):
            raise HTTPException(status_code=400, detail={"error":"build_jobs_failed","details":build_res})
        jobs_path = build_res["jobs_path"]

    try:
        t0 = time.time()
        results = nightly_recalibrate_from_jobs(jobs_path)
        return {"ok": True, "jobs": jobs_path, "results": results, "elapsed_sec": round(time.time()-t0,2)}
    except Exception as e:
        return {"ok": False, "error": "run_failed", "details": str(e), "jobs": jobs_path}


