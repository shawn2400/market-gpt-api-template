# server_routes.py
from fastapi import FastAPI, HTTPException, Depends, Query
from pydantic import BaseModel
from server_signing import verify_signature

app = FastAPI()

# אופציונלי: תלות שמאמת Bearer (אם נדרש)
def require_bearer(authorization: str | None = None):
    # אם מחייבים Bearer — אמתו כאן וזרקו 401/403 במקרה הצורך.
    # אם לא — הפונקציה יכולה להיות no-op או לא להיקרא בכלל.
    return True

class ApproveResponse(BaseModel):
    ok: bool
    ticket_id: str
    detail: str | None = None

@app.get("/ops/approve/signed", response_model=ApproveResponse)
def approve_signed(
    ticket_id: str = Query(...),
    exp: str = Query(...),
    sig: str = Query(...),
    _auth_ok: bool = Depends(require_bearer)  # בטלו אם לא מחייבים Bearer
):
    ok, why = verify_signature(ticket_id, exp, sig)
    if not ok:
        # החזירו 401 עם פירוט מסייע (לוגים מלאים בצד השרת)
        raise HTTPException(status_code=401, detail=f"Bad signature: {why}")

    # בצעו את אישור הטיקט בפועל (טרנזקציה/קריאת בורסה/וכו׳)
    # אם צריך, ודאו שהטיקט קיים/לא בוטל/לא אושר כבר.
    return ApproveResponse(ok=True, ticket_id=ticket_id, detail="approved")
