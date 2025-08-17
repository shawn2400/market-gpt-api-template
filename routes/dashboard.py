# routes/dashboard.py
from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter()

@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard_ui():
    return """
    <html>
        <head>
            <meta charset="utf-8">
            <title>AlgoGPT Dashboard</title>
        </head>
        <body>
            <h1>📊 AlgoGPT Dashboard</h1>
            <p>UI תצוגה חזותית תגיע בקרוב (React/Vite או תבנית)</p>
        </body>
    </html>
    """

