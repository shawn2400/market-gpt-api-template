# routes/debug.py
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter(prefix="/debug", tags=["Debug"])

@router.post("/headers", include_in_schema=False)
async def debug_headers(request: Request):
    headers = dict(request.headers)
    try:
        body = await request.json()
    except Exception:
        body = None
    return JSONResponse(content={"headers": headers, "body": body})
