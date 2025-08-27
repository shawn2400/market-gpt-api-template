# בתוך routes/executor.py – הוסף מתחת לייבוא הקיימים
import time
from functools import lru_cache

# מודל תגובת Health
class HealthResponse(BaseModel):
    ok: bool = True
    binance_ping: bool
    signed_balance_ok: bool
    mark_price_ok: bool
    details: Dict[str, Any] = Field(default_factory=dict)
    cached: bool = False
    ttl_seconds: int = 10

# Cache פשוט ל-10 שניות
_health_cache: Dict[str, Any] = {"ts": 0.0, "data": None}
_HEALTH_TTL = 10  # שניות

@router.get("/health", response_model=HealthResponse)
def health_check(symbol: str = Query("BTCUSDT", min_length=3, max_length=20)) -> HealthResponse:
    """
    בדיקת בריאות קלת-משקל:
    - ping ציבורי ל-Binance Futures
    - קריאה חתומה קטנה (balance) לאימות מפתחות/הרשאות
    - Mark Price לסימבול (ברירת מחדל BTCUSDT)
    תוצאת הבדיקה נשמרת ל-10 שניות כדי למנוע עומס.
    """
    now = time.time()
    if _health_cache["data"] and (now - _health_cache["ts"] < _HEALTH_TTL):
        resp: HealthResponse = _health_cache["data"]
        # מציין שזו תוצאה מה-Cache
        return HealthResponse(**resp.dict(), cached=True)

    details: Dict[str, Any] = {}
    # 1) Ping ציבורי
    try:
        ping_ok = bool(fapi_ping())
    except Exception as e:
        ping_ok = False
        details["ping_error"] = str(e)

    # 2) חתום: balance (קטן ומהיר)
    try:
        bal = futures_balance()
        signed_ok = isinstance(bal, list)
        if not signed_ok:
            details["balance_raw"] = bal
    except Exception as e:
        signed_ok = False
        details["balance_error"] = str(e)

    # 3) Mark price
    try:
        mp = futures_mark_price(symbol)
        mp_ok = (mp is not None)
        if mp_ok:
            details["mark_price"] = mp
        else:
            details["mark_price_error"] = f"No mark price for {symbol}"
    except Exception as e:
        mp_ok = False
        details["mark_price_error"] = str(e)

    ok = ping_ok and signed_ok and mp_ok
    resp = HealthResponse(
        ok=ok,
        binance_ping=ping_ok,
        signed_balance_ok=signed_ok,
        mark_price_ok=mp_ok,
        details=details,
        cached=False,
    )
    _health_cache["ts"] = now
    _health_cache["data"] = resp
    return resp




















