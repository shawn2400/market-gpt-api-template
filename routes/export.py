# routes/export.py
from fastapi import APIRouter, Depends, Query
from fastapi.responses import FileResponse
from datetime import datetime
from utils.auth import require_api_key
from utils.export_utils import generate_daily_csv_report, generate_daily_pdf_report
import os

router = APIRouter(
    prefix="/export",
    tags=["Export"],
    dependencies=[Depends(require_api_key)]
)

@router.get("/csv")
def export_csv():
    path = generate_daily_csv_report()
    return FileResponse(path, filename=os.path.basename(path))

@router.get("/pdf")
def export_pdf():
    path = generate_daily_pdf_report()
    return FileResponse(path, filename=os.path.basename(path))

