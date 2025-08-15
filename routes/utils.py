# routes/utils.py
from fastapi import APIRouter, Query, Depends
from typing import Optional
from utils.auth import require_bearer_token
from utils.generate_logo import generate_logo

router = APIRouter(prefix="/utils", tags=["Utils"], dependencies=[Depends(require_bearer_token)])

@router.get("/generate-logo", summary="Generate a simple text logo (PNG/ICO/SVG on server)")
async def generate_logo_api(
    text: str = Query("AlgoGPT", description="טקסט הלוגו"),
    size: int = Query(512, ge=64, le=2048, description="גודל התמונה (ריבוע)"),
    dark_bg: bool = Query(True, description="רקע כהה (True) או בהיר (False)"),
    transparent: bool = Query(False, description="רקע שקוף"),
    filename: Optional[str] = Query(None, description="נתיב יעד (ברירת מחדל: static/logo.png)"),
):
    out = generate_logo(
        text=text,
        filename=filename or "static/logo.png",
        size=size,
        dark_bg=dark_bg,
        transparent=transparent,
        add_glow=True,
    )
    base = out.rsplit(".", 1)[0]
    return {
        "ok": True,
        "png": out,
        "ico": f"{base}.ico",
        "svg": f"{base}.svg",
        "params": {"text": text, "size": size, "dark_bg": dark_bg, "transparent": transparent},
    }

   
