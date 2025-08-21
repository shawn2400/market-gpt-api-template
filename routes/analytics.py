from fastapi import APIRouter, Query
from pydantic import BaseModel
from utils.storage import save_payload, cleanup_static

router = APIRouter(tags=["Analytics"])


class AnalyticsResponse(BaseModel):
    ok: bool = True
    url: str   # ✅ מחזירים URL מלא


@router.get("/generate", response_model=AnalyticsResponse)
async def generate_analytics(symbol: str = Query(...)):
    """
    יוצר דוח אנליזה כבד → שומר בקובץ static.
    מחזיר ללקוח URL יחסי (/static/cache/...).
    """
    fake_data = {
        "symbol": symbol,
        "note": "this would normally contain chart/indicators"
    }
    url = save_payload(fake_data, expire=3600)
    cleanup_static()

    return AnalyticsResponse(ok=True, url=url)










































