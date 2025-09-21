from fastapi import APIRouter
router = APIRouter(prefix="/telegram", tags=["Telegram"])

@router.get("/ping", summary="Ping")
async def ping():
    return {"ok": True}






