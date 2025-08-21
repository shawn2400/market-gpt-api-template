from fastapi import APIRouter, Query
from pydantic import BaseModel
from utils.storage import save_payload, cleanup_static

router = APIRouter(tags=["News"])


class NewsResponse(BaseModel):
    ok: bool = True
    url: str


@router.get("/latest", response_model=NewsResponse)
async def latest_news(limit: int = Query(20, ge=1, le=100)):
    """
    מביא חדשות → שומר בקובץ static → מחזיר URL.
    """
    fake_news = [{"title": f"News {i}", "source": "CryptoPanic"} for i in range(limit)]
    url = save_payload({"items": fake_news}, expire=600)
    cleanup_static()

    return NewsResponse(ok=True, url=url)











