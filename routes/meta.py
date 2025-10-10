# routes/meta.py
from fastapi import APIRouter
import os
try:
    import importlib.metadata as md  # py3.8+
except Exception:  # very old pythons
    md = None

router = APIRouter()

def detect_version() -> str:
    # 1) ENV (הכי זמין)
    v = os.getenv("ALGOGPT_VERSION") or os.getenv("APP_VERSION")
    if v:
        return str(v).strip()

    # 2) קובץ VERSION אם קיים
    for p in ("VERSION", "/app/VERSION"):
        try:
            with open(p, "r", encoding="utf-8") as f:
                vv = f.read().strip()
                if vv:
                    return vv
        except Exception:
            pass

    # 3) מטא-דאטה של חבילה (אם קימפלתם כ-package)
    if md:
        for name in ("algogpt", "AlgoGPT"):
            try:
                return md.version(name)
            except Exception:
                pass

    # 4) ברירת מחדל אחרונה
    return "unknown"

@router.get("/meta/version")
def meta_version():
    return {
        "ok": True,
        "service": os.getenv("APP_TITLE", "AlgoGPT"),
        "version": detect_version(),
        "instance": os.getenv("INSTANCE_ID", "default"),
    }
