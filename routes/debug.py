# routes/debug.py
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter()

@router.post("/headers", tags=["Debug"])
async def debug_headers(request: Request):
    """
    מחזיר את ה־headers + body בדיוק כפי שהתקבלו.
    מאפשר בדיקה האם Authorization / X-API-KEY באמת מגיעים לשרת.
    """
    headers = dict(request.headers)
    try:
        body = await request.json()
    except Exception:
        body = None
    return JSONResponse(content={"headers": headers, "body": body})

