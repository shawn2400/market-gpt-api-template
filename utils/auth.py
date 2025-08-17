# utils/auth.py
from fastapi import Header, HTTPException, status

# תלות לשימוש עם Depends(...) שמחזירה None בלבד
async def require_bearer_token(authorization: str = Header(default="")) -> None:
    """
    מוודאת שיש כותרת Authorization בפורמט 'Bearer <token>'.
    החזר ערך הוא None (כך שלא יחשב כ-Request).
    """
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid bearer token",
        )
    token = authorization.split(" ", 1)[1].strip()
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Empty token",
        )
    # אפשר להוסיף פה בדיקה מול סוד/DB וכו'
    return None




