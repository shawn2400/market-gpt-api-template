from fastapi import Header, HTTPException
import os

# מפתח API מה־.env
API_BEARER_TOKEN = os.getenv("API_BEARER_TOKEN", "").strip()

def require_api_key(authorization: str = Header(None)):
    """
    Middleware פשוט להגנה על ה־API.
    בודק Authorization: Bearer <TOKEN> מול API_BEARER_TOKEN מה־.env
    """
    if not API_BEARER_TOKEN:
        # אם לא הוגדר מפתח בכלל – לא ננעל (מצב DEV)
        return True

    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Authorization header")

    token = authorization.replace("Bearer", "").strip()
    if token != API_BEARER_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid API key")

    return True






































