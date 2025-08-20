# routes/debug.py
from fastapi import APIRouter, Request

router = APIRouter(tags=["Debug"])

@router.post("/debug/headers")
async def debug_headers(req: Request):
    return {
        "headers": dict(req.headers),
        "query_params": dict(req.query_params),
    }
