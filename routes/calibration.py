# routes/calibration.py
from fastapi import APIRouter, Depends
from utils.auth import require_api_key
from calibration.search import nightly_recalibrate_from_jobs
import os

router = APIRouter(prefix="/calib", tags=["calibration"], dependencies=[Depends(require_api_key)])

@router.post("/run")
async def run_calib(batch_path: str | None = None):
    p = batch_path or os.getenv("CALIB_JOBS_PATH","config/calib_jobs.json")
    res = nightly_recalibrate_from_jobs(p)
    return {"ok": True, "results": res}
