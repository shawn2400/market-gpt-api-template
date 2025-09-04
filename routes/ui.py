# routes/ui.py
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
import os

router = APIRouter(
    prefix="/ui",
    tags=["UI"]
)

@router.get("/dashboard", include_in_schema=False)
async def serve_dashboard():
    path = os.path.join("static", "dashboard", "index.html")
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Dashboard not found")
    return FileResponse(path, media_type="text/html")


