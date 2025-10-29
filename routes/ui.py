from __future__ import annotations
from fastapi import APIRouter
from fastapi.responses import FileResponse, Response
from pathlib import Path

router = APIRouter(tags=["UI"])

@router.get("/dashboard")
def dashboard_ui():
    path = Path("static/dashboard/index.html")
    if path.exists():
        resp = FileResponse(path)
        # cache קצר – למנוע עומסים
        resp.headers["Cache-Control"] = "private, max-age=30"
        return resp
    return {"error": "dashboard not found"}



