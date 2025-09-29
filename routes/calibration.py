# routes/calibration.py  (LIVE)
from __future__ import annotations
import os, json
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
    # נרמל אותיות גדולות
    return [w.upper() for w in wl]

def _tfs() -> List[str]:
    tfs = _env_csv("INDICATOR_INTERVALS", "15m,1h")
    return tfs

def _load_trades_log(path: str) -> List[Dict[str, Any]]:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"trades_log not found: {p}")
    raw = json.loads(p.read_text(encoding="utf-8"))
    if isinstance(raw, list):
        return raw
    if isinstance(raw, dict):
        # אפשרי פורמטים שונים: {"rows":[...]} / {"data":[...]}
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
    if val is None:
        return None
    # מספר => נניח ms
    if isinstance(val, (int, float)):
        try:
            return datetime.fromtimestamp(float(val)/1000.0, tz=timezone.utc).isoformat()
        except Exception:
            return None
    # מחרוזת
    s = str(val)
    try:
        return datetime.fromisoformat(s.replace("Z","+00:00")).astimezone(timezone.utc).isoformat()
    except Exception:
        # נסה שנית – אם זה שניות
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

# grids קטנים ומהירים – אפשר להרחיב בהמשך פר אינדיקטור
DEFAULT_PARAM_GRIDS: Dict[str, Dict[str, List[Any]]] = {
    "mc_b": {"rsi_len": [14, 21], "vwma_len": [20, 30]},
    "alpha": {"atr_mult": [1.2, 1.6], "atr_len": [10, 14]},
    "qqe": {"len": [14, 21], "factor": [3.0, 4.0]},
}

# -------------------- Schemas --------------------
class BuildJobsRequest(BaseDict:=Dict[str, Any]):  # Pydantic-free, FastAPI יקבל dict
    pass

class RunLiveRequestModel:
    # משתמשים ב-Body(..., embed=False) כדי לקבל dict חופשי
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
      - indicators: ['mc_b','alpha','qqe', ...]
      - param_grids: {name: {param: [values...]}}
      - tol_bars: ברירת מחדל 1
      - limit: ברירת מחדל 800 (מספר נרות לטעינה לכיול)
    """
    trades_log_path = req.get("trades_log_path") or "data/trades_log.json"
    indicators: List[str] = req.get("indicators") or ["mc_b", "alpha", "qqe"]
    param_grids: Dict[str, Dict[str, List[Any]]] = {**DEFAULT_PARAM_GRIDS, **(req.get("param_grids") or {})}
    tol_bars = int(req.get("tol_bars", 1))
    limit = int(req.get("limit", 800))
    market = req.get("market", os.getenv("DEFAULT_MARKET","futures"))

    rows = _load_trades_log(trades_log_path)
    ref_by_key = _extract_ref_by_symbol_tf(rows, _watchlist(), _tfs())

    # כתיבת קבצי ref_signals לכל צמד/TF
    ref_files: Dict[str, str] = {}
    for key, arr in ref_by_key.items():
        dst = f"data/ref_signals_{key.lower()}.json"
        _write_json(dst, arr)
        ref_files[key] = dst

    # יצירת jobs list
    jobs = []
    for key in sorted(ref_by_key.keys()):
        sym, tf = key.split("_", 1)
        for name in indicators:
            grid = param_grids.get(name) or {}
            # ref_signals ישירות – כדי לא לדרוש I/O נוסף בזמן ריצה
            try:
                ref = json.loads(Path(ref_files[key]).read_text(encoding="utf-8"))
            except Exception:
                ref = []
            jobs.append({
                "symbol": sym,
                "tf": tf,
                "name": name,
                "param_grid": grid,
                "ref_signals": ref,
                "tol_bars": tol_bars,
                "limit": limit,
                "market": market,
            })

    jobs_path = _jobs_default_path()
    _write_json(jobs_path, jobs)
    return {"ok": True, "jobs_path": jobs_path, "jobs_count": len(jobs), "refs_written": list(ref_files.values())}

@router.post("/run-live")
def run_live(req: Dict[str, Any] = Body(default={})):
    """
    זרימה מלאה בלייב: אם חסר calib_jobs.json — יבנה אותו מיידית מ-trades_log.json, ואז יריץ כיול.
    Body (אופציונלי – כמו build-jobs):
      trades_log_path / indicators / param_grids / tol_bars / limit / market / jobs_path
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
        results = nightly_recalibrate_from_jobs(jobs_path)
        return {"ok": True, "jobs": jobs_path, "results": results}
    except Exception as e:
        return {"ok": False, "error": "run_failed", "details": str(e), "jobs": jobs_path}

