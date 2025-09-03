// routes/ui.py
from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse
from utils.auth import require_api_key
import os

router = APIRouter(
    prefix="/ui",
    tags=["UI"],
    dependencies=[Depends(require_api_key)]
)

@router.get("/dashboard")
async def serve_dashboard():
    path = os.path.join("static", "dashboard", "index.html")
    return FileResponse(path, media_type="text/html")

