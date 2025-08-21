# utils/auth.py
from fastapi import Header, HTTPException, status, Depends
import os

# --- Load API Key from env ---
API_KEY = os.getenv("API_KEY", "changeme")  # לשים ב־.env: API_KEY=xxxxx
API_KEY_HEADER = os.getenv("API_KEY_HEADER", "X-API-KEY")

async def verify_api_key(x_api_key: str = Header(None)) -> None:
    """
    מאמת בקשות לפי API-KEY שמועבר ב־Header (ברירת מחדל X-API-KEY).
    """
    if not x_api_key or x_api_key != API_KEY:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API Key",
        )

# --- Dependency לשימוש ב־routes ---
def require_api_key(dep=Depends(verify_api_key)):
    return dep




































