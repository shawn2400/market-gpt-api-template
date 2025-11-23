from fastapi import Request, HTTPException

def verify_admin(request: Request, admin_token: str):
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    if token != admin_token:
        raise HTTPException(status_code=401, detail="Unauthorized")
