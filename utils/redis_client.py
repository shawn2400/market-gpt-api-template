# utils/redis_client.py
from __future__ import annotations

import os
import ssl
import time
import logging
from typing import Optional, Tuple
from urllib.parse import urlparse, parse_qs, urlunsplit

try:
    import redis  # redis-py
except Exception as e:  # pragma: no cover
    raise RuntimeError(f"redis module is required: {e}")

_LOG = logging.getLogger("algogpt.redis")

# -------------------- Env & defaults --------------------
def _env_bool(name: str, default: str = "0") -> bool:
    return (os.getenv(name, default) or "").strip().lower() in {"1", "true", "on", "yes"}

def get_redis_url() -> str:
    return os.getenv("REDIS_URL", "").strip()

def _timeouts() -> Tuple[float, float]:
    # נשמר מעט נדיב מול עננים (Render וכו')
    conn_to = float(os.getenv("REDIS_CONNECT_TIMEOUT_SEC", os.getenv("REDIS_CONNECT_TIMEOUT", "5")) or 5)
    sock_to = float(os.getenv("REDIS_SOCKET_TIMEOUT_SEC", os.getenv("REDIS_SOCKET_TIMEOUT", "5")) or 5)
    return conn_to, sock_to

POOL_MAX_CONNECTIONS = int(os.getenv("REDIS_POOL_MAX_CONNECTIONS", "30"))
CLIENT_NAME          = os.getenv("REDIS_CLIENT_NAME", "algogpt")
SSL_NO_VERIFY_ENV    = _env_bool("REDIS_SSL_NO_VERIFY", "0")
PING_RETRIES         = int(os.getenv("REDIS_PING_RETRIES", "2"))
PING_BACKOFF_SEC     = float(os.getenv("REDIS_PING_RETRY_BACKOFF_SEC", "0.3"))
RETRY_ON_TIMEOUT     = _env_bool("REDIS_RETRY_ON_TIMEOUT", "1")
SSL_CA_CERTS_PATH    = os.getenv("REDIS_SSL_CA_CERTS", "").strip()  # אופציונלי

# -------------------- Helpers --------------------
def _mask_url(url: str) -> str:
    try:
        p = urlparse(url)
        host = p.hostname or ""
        # IPv6 netloc needs brackets if we ever displayed it, but לשם לוג זה מספיק.
        netloc = host
        if p.port:
            netloc += f":{p.port}"
        return urlunsplit((p.scheme, netloc, p.path, p.query, p.fragment))
    except Exception:
        return "<unparseable>"

def _map_cert(val: str) -> int:
    v = (val or "").strip().lower()
    # תמיכה גם בערכים בוליאניים/מספריים/מחרוזיים
    if v in {"none", "no", "0", "off", "false"}:
        return ssl.CERT_NONE
    if v in {"optional", "1", "on", "true"}:
        return ssl.CERT_OPTIONAL
    # required כברירת מחדל
    return ssl.CERT_REQUIRED

# -------------------- Client factory --------------------
def make_client(*, decode: bool = True) -> "redis.Redis":
    """
    יוצר לקוח Redis יציב עם TLS נכון.
    חשוב: לא שולחים kw בשם 'ssl', כדי להימנע מהשגיאה:
      AbstractConnection.__init__() got an unexpected keyword argument 'ssl'
    במקום זאת בוחרים connection_class=SSLConnection ומעבירים ssl_cert_reqs בלבד.
    """
    url = get_redis_url()
    if not url:
        raise RuntimeError("REDIS_URL not set")

    parsed = urlparse(url)
    qs = parse_qs(parsed.query or "")
    conn_to, sock_to = _timeouts()

    # ארגומנטים כלליים — יעבדו גם ל-redis:// וגם ל-rediss://
    kwargs = dict(
        socket_connect_timeout=conn_to,
        socket_timeout=sock_to,
        decode_responses=decode,
        client_name=CLIENT_NAME,
        max_connections=POOL_MAX_CONNECTIONS,
        socket_keepalive=True,
        retry_on_timeout=RETRY_ON_TIMEOUT,
    )

    scheme = (parsed.scheme or "").lower()
    if scheme == "rediss":
        # ב-TLS נשתמש במחלקת SSLConnection; לא מעבירים ssl=True.
        from redis.connection import SSLConnection
        # קדימות לפרמטר ב-URL, אחרת מה-ENV, ברירת מחדל required
        cert_str = qs.get("ssl_cert_reqs", [os.getenv("REDIS_SSL_CERT_REQS", "required")])[0]
        cert_req = _map_cert(cert_str)

        # אם ביקשו לבטל אימות דרך ENV (בדיקות), נאכוף CERT_NONE — אלא אם ה-URL ביקש required במפורש
        if SSL_NO_VERIFY_ENV and cert_str.strip().lower() not in {"required"}:
            cert_req = ssl.CERT_NONE

        kwargs.update(
            connection_class=SSLConnection,
            ssl_cert_reqs=cert_req,
        )

        # אם סופק CA ייעודי — נעביר
        if SSL_CA_CERTS_PATH:
            kwargs["ssl_ca_certs"] = SSL_CA_CERTS_PATH
    else:
        from redis.connection import Connection
        kwargs.update(connection_class=Connection)

    # יצירה מה-URL (כולל קרדנציאלס/הוסט/פורט/DB ושאר query params)
    cli = redis.from_url(url, **kwargs)
    return cli

# -------------------- Singleton + accessors --------------------
_redis_singleton: Optional["redis.Redis"] = None

def _init_singleton() -> Optional["redis.Redis"]:
    global _redis_singleton
    url = get_redis_url()
    if not url:
        _LOG.info({"event": "redis.disabled", "reason": "REDIS_URL missing"})
        _redis_singleton = None
        return None
    try:
        cli = make_client()
        # Ping עם ריטריים קלים בזמן עלייה
        last_err = None
        ok = False
        for i in range(PING_RETRIES + 1):
            try:
                if cli.ping():
                    ok = True
                    break
            except Exception as e:
                last_err = e
                if i < PING_RETRIES:
                    time.sleep(PING_BACKOFF_SEC)
        if ok:
            _LOG.info({"event": "redis.connected", "url": _mask_url(url)})
        else:
            _LOG.warning({"event": "redis.ping_failed", "error": str(last_err)})
        # גם אם ה-PING נכשל — נשמור את האובייקט; ייתכן שאח"כ יצליח
        _redis_singleton = cli
        return cli
    except Exception as e:
        _LOG.warning({"event": "redis.unavailable", "error": str(e), "url": _mask_url(url)})
        _redis_singleton = None
        return None

def get_redis() -> Optional["redis.Redis"]:
    """
    החזר את הלקוח הסינגלטון אם הוקם, אחרת נסה להקים.
    """
    global _redis_singleton
    if _redis_singleton is not None:
        return _redis_singleton
    return _init_singleton()

# אליאס היסטורי — אם מישהו מייבא את השם הזה ישירות
redis_client: Optional["redis.Redis"] = get_redis()

# -------------------- Utilities --------------------
def ping_safe() -> bool:
    """
    מחזיר True אם ניתן לעשות PING כרגע; לא מרים חריגות החוצה.
    """
    try:
        r = get_redis()
        if not r:
            return False
        return bool(r.ping())
    except Exception as e:
        _LOG.warning({"event": "redis.ping_failed", "error": str(e)})
        return False

__all__ = ["make_client", "get_redis", "redis_client", "ping_safe"]










