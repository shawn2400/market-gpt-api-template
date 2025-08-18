# routes/dashboard.py
from fastapi import APIRouter
from fastapi.responses import HTMLResponse, Response

router = APIRouter(tags=["Dashboard"])

_HTML = """<!doctype html> ... (התוכן הקיים שלך) ... </html>"""

@router.api_route(
    "/dashboard",
    methods=["GET", "HEAD"],
    response_class=HTMLResponse,
    operation_id="getDashboardHtml_v2",  # <- שינוי השם כדי למנוע duplicate
)
async def dashboard_ui():
    return Response(content=_HTML, media_type="text/html")









