# ===== קובץ: routes/multi_scan.py =====

from fastapi import APIRouter
from utils.multi_tf_scanner import multi_tf_scan_with_ai

router = APIRouter()

@router.get("/scan/multi")
async def multi_tf_scan_api(min_quality: int = 6, top: int = 10):
    results = await multi_tf_scan_with_ai(min_quality=min_quality, top=top)
    return {"results": results}
