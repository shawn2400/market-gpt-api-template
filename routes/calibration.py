# routes/calibration.py
from __future__ import annotations
import os, json
from pathlib import Path
from typing import Optional, List, Dict, Any

from fastapi import APIRouter, Depends, Body
from pydantic import BaseModel, Field

# --- Auth dependency (זהה לפרויקט) ---
try:
    from utils.auth import require_api_key
except Exception:
    def require_api_key():
        return True

from calibration.search import nightly_recalibrate_from_jobs
from utils.indicators_registry import PARAMS_DIR

router = APIRouter(prefix="/calib", tags=["calibration"], dependencies=[Depends(require_api_key)])

# ---------- Schemas ----------
class RunRequest(BaseModel):
    jobs_path: Optional[str] = Field(default=None, description="ברירת מחדל: CALIB_JOBS_PATH או config/calib_jobs.json")
    force_enable: Optional[bool] = Field(default=False, description="להכריח ריצה גם אם CALIB_ENABLE!=1")

class ExtractAndRunRequest(BaseModel):
    src_trades_log: str = Field(..., description="נתיב ל-data/trades_log.json או דומה")
    outputs: Dict[str, str] = Field(..., description="מיפוי label→נתיב ל-ref_signals.json")
    run_jobs_path: Optional[str] = Field(default=None, description="אם ניתן — יריץ מיד אחרי הייצור")

# ---------- Helpers ----------
def _calib_enabled(force: bool = False) -> bool:
    if force:
        return True
    return str(os.getenv("CALIB_ENABLE", "0")).lower() in ("1", "true", "yes", "on")

def _extract_ref_signals(src_path: str) -> List[Dict[str, Any]]:
    """מייצר ref_signals = [{ 'ts': ISO8601, 'side':'long'|'short' }] מתוך trades_log.json."""
    from datetime import datetime, timezone
    def norm_side(x: str) -> str:
        x = (x or "").lower()
        if x in ("long","buy","open_long","tp_long","tp1_long"): return "long"
        if x in ("short","sell","open_short","tp_short","tp1_short"): return "short"
        return "neutral"
    def to_ts(val):
        if isinstance(val,(int,float)):
            return datetime.fromtimestamp(float(val)/1000.0, tz=timezone.utc).isoformat()
        s = str(val or "")
        try:
            return datetime.fromisoformat(s.replace("Z","+00:00")).astimezone(timezone.utc).isoformat()
        except Exception:
            return None

    raw = json.loads(Path(src_path).read_text(encoding="utf-8"))
    rows = raw if isinstance(raw, list) else raw.get("rows") or []
    out = []
    for r in rows:
        ts = r.get("ts") or r.get("close_time") or r.get("time")
        side = r.get("side") or r.get("action") or r.get("dir")
        ts = to_ts(ts); side = norm_side(side)
        if ts and side in ("long","short"):
            out.append({"ts": ts, "side": side})
    return out

def _jobs_default_path() -> str:
    return os.getenv("CALIB_JOBS_PATH", "config/calib_jobs.json")

# ---------- Routes ----------
@router.get("/ping")
def calib_ping():
    return {
        "ok": True,
        "enabled": _calib_enabled(),
        "params_dir": str(PARAMS_DIR),
        "jobs_default": _jobs_default_path(),
    }

@router.get("/status")
def calib_status():
    """רשימת קבצי פרמטרים קיימים (בדיקת post-run מהירה)."""
    items = []
    if PARAMS_DIR.exists():
        for p in sorted(PARAMS_DIR.glob("*.json")):
            try:
                st = p.stat()
                items.append({"file": p.name, "size": st.st_size, "mtime": int(st.st_mtime)})
            except Exception:
                items.append({"file": p.name})
    return {"ok": True, "count": len(items), "items": items}

@router.post("/run")
def calib_run(req: RunRequest = Body(default=RunRequest())):
    if not _calib_enabled(req.force_enable):
        return {"ok": False, "error": "calibration_disabled", "hint": "Set CALIB_ENABLE=1 or force_enable=true"}

    jobs_path = req.jobs_path or _jobs_default_path()
    p = Path(jobs_path)
    if not p.exists():
        return {"ok": False, "error": "jobs_not_found", "path": str(p)}

    try:
        results = nightly_recalibrate_from_jobs(str(p))
        return {"ok": True, "jobs": str(p), "results": results}
    except Exception as e:
        return {"ok": False, "error": "run_failed", "details": str(e), "jobs": str(p)}

@router.post("/extract-and-run")
def calib_extract_and_run(req: ExtractAndRunRequest):
    """1) ייצור ref_signals.json לפי קלט, 2) ריצה מיידית אם run_jobs_path צוין."""
    try:
        base_refs = _extract_ref_signals(req.src_trades_log)
        for _, dst in req.outputs.items():
            Path(dst).parent.mkdir(parents=True, exist_ok=True)
            Path(dst).write_text(json.dumps(base_refs, ensure_ascii=False, indent=2), encoding="utf-8")
        out = {"ok": True, "written": list(req.outputs.values())}
    except Exception as e:
        return {"ok": False, "error": "extract_failed", "details": str(e)}

    if req.run_jobs_path:
        run_res = calib_run(RunRequest(jobs_path=req.run_jobs_path, force_enable=True))
        out["run"] = run_res
    return out

@router.post("/bootstrap-demo")
def calib_bootstrap_demo():
    """
    דוגמת כיול מוכנה: בונה ref_signals בסיסי ומריץ jobs עבור:
      BTCUSDT/ETHUSDT על 15m ו-1h, אינדיקטורים: mc_b, alpha, qqe.
    שימוש: POST /calib/bootstrap-demo
    """
    if not _calib_enabled(True):
        return {"ok": False, "error": "calibration_disabled"}

    # 1) ref_signals demo (ריק/מינימלי – תוכל להחליף אח"כ ב-Extract-and-Run אמיתי)
    Path("data").mkdir(parents=True, exist_ok=True)
    demo_refs = [{"ts": "2024-01-01T00:00:00+00:00", "side": "long"}]
    ref_map = {
        "BTCUSDT_15m": "data/ref_signals_btc_15m.json",
        "BTCUSDT_1h":  "data/ref_signals_btc_1h.json",
        "ETHUSDT_15m": "data/ref_signals_eth_15m.json",
        "ETHUSDT_1h":  "data/ref_signals_eth_1h.json",
    }
    for dst in ref_map.values():
        Path(dst).write_text(json.dumps(demo_refs, ensure_ascii=False, indent=2), encoding="utf-8")

    # 2) config/calib_jobs.json
    Path("config").mkdir(parents=True, exist_ok=True)
    jobs_path = _jobs_default_path()
    jobs = [
        # BTC
        {"symbol":"BTCUSDT","tf":"15m","name":"mc_b","param_grid":{"rsi_len":[14,21]}, "ref_signals_path":ref_map["BTCUSDT_15m"]},
        {"symbol":"BTCUSDT","tf":"15m","name":"alpha","param_grid":{"atr_mult":[1.2,1.6]}, "ref_signals_path":ref_map["BTCUSDT_15m"]},
        {"symbol":"BTCUSDT","tf":"15m","name":"qqe","param_grid":{"len":[14,21]}, "ref_signals_path":ref_map["BTCUSDT_15m"]},
        {"symbol":"BTCUSDT","tf":"1h","name":"mc_b","param_grid":{"rsi_len":[14,21]}, "ref_signals_path":ref_map["BTCUSDT_1h"]},
        {"symbol":"BTCUSDT","tf":"1h","name":"alpha","param_grid":{"atr_mult":[1.2,1.6]}, "ref_signals_path":ref_map["BTCUSDT_1h"]},
        {"symbol":"BTCUSDT","tf":"1h","name":"qqe","param_grid":{"len":[14,21]}, "ref_signals_path":ref_map["BTCUSDT_1h"]},
        # ETH
        {"symbol":"ETHUSDT","tf":"15m","name":"mc_b","param_grid":{"rsi_len":[14,21]}, "ref_signals_path":ref_map["ETHUSDT_15m"]},
        {"symbol":"ETHUSDT","tf":"15m","name":"alpha","param_grid":{"atr_mult":[1.2,1.6]}, "ref_signals_path":ref_map["ETHUSDT_15m"]},
        {"symbol":"ETHUSDT","tf":"15m","name":"qqe","param_grid":{"len":[14,21]}, "ref_signals_path":ref_map["ETHUSDT_15m"]},
        {"symbol":"ETHUSDT","tf":"1h","name":"mc_b","param_grid":{"rsi_len":[14,21]}, "ref_signals_path":ref_map["ETHUSDT_1h"]},
        {"symbol":"ETHUSDT","tf":"1h","name":"alpha","param_grid":{"atr_mult":[1.2,1.6]}, "ref_signals_path":ref_map["ETHUSDT_1h"]},
        {"symbol":"ETHUSDT","tf":"1h","name":"qqe","param_grid":{"len":[14,21]}, "ref_signals_path":ref_map["ETHUSDT_1h"]},
    ]

    # הפוך ref_signals_path → ref_signals בפועל כדי להתאים ל-nightly_recalibrate_from_jobs
    for j in jobs:
        try:
            j["ref_signals"] = json.loads(Path(j.pop("ref_signals_path")).read_text(encoding="utf-8"))
        except Exception:
            j["ref_signals"] = []

    Path(jobs_path).write_text(json.dumps(jobs, ensure_ascii=False, indent=2), encoding="utf-8")

    # 3) ריצה
    try:
        results = nightly_recalibrate_from_jobs(jobs_path)
        return {"ok": True, "jobs": jobs_path, "results": results}
    except Exception as e:
        return {"ok": False, "error": "bootstrap_failed", "details": str(e)}
