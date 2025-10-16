from fastapi import APIRouter
import os
try:
    import importlib.metadata as md  # py3.8+
except Exception:
    md = None

router = APIRouter()

def detect_version() -> str:
    # 1) ENV
    v = os.getenv("ALGOGPT_VERSION") or os.getenv("APP_VERSION")
    if v:
        return str(v).strip()

    # 2) קובץ VERSION
    for p in ("VERSION", "/app/VERSION"):
        try:
            with open(p, "r", encoding="utf-8") as f:
                vv = f.read().strip()
                if vv:
                    return vv
        except Exception:
            pass

    # 3) מטא של החבילה (אם קיימת)
    if md:
        for name in ("algogpt", "AlgoGPT"):
            try:
                return md.version(name)
            except Exception:
                pass

    return "unknown"

@router.get("/meta/version", tags=["meta"])
def meta_version():
    return {
        "ok": True,
        "service": os.getenv("APP_TITLE", "AlgoGPT"),
        "version": detect_version(),
        "instance": os.getenv("INSTANCE_ID", "default"),
    }

