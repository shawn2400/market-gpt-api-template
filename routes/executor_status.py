# routes/executor_status.py
from fastapi import APIRouter
from utils.runtime_counters import get_executor_status

router = APIRouter(prefix="/executor", tags=["executor"])

@router.get("/status")
async def executor_status():
    return {"ok": True, "status": get_executor_status()}
