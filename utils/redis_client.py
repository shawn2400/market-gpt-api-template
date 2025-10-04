# utils/redis_client.py
from __future__ import annotations

import os
import ssl
import logging
from urllib.parse import urlparse, parse_qs
import redis

_LOG = logging.getLogger("algogpt.redis")


def get_redis_url() -> str:
    return os.getenv("REDIS_URL", "").strip()


def _timeouts():
    conn_to = float(os.getenv("REDIS_CONNECT_TIMEOUT_SEC", "5") or 5)
    sock_to = float(os.getenv("REDIS_SOCKET_TIMEOUT_SEC", "5") or 5)
    return conn_to, sock_to


def _map_cert(val: str) -> int:
    v = (val or "").strip().lower()
    if v in ("none", "no", "0", "off", "false"):
        return ssl.CERT_NONE
    if v in ("optional", "1", "on", "true"):
        return ssl.CERT_OPTIONAL
    return ssl.CERT_REQUIRED


def make_client(*, decode: bool = True) -> "redis.Redis":
    """
    יוצר לקוח Redis יציב עם ניהול SSL נכון:
    - ב-rediss://: כופה connection_class=SSLConnection וממפה ssl_cert_reqs לערכי ssl.CERT_*
      כדי להימנע מהשגיאה: AbstractConnection.__init__() got an unexpected keyword argument 'ssl'
    - מוסיף timeouts ברירת מחדל (או מ-ENV)
    """
    url = get_redis_url()
    if not url:
        raise RuntimeError("REDIS_URL not set")

    parsed = urlparse(url)
    qs = parse_qs(parsed.query or "")
    conn_to, sock_to = _timeouts()
    kwargs = dict(socket_connect_timeout=conn_to, socket_timeout=sock_to, decode_responses=decode)

    scheme = (parsed.scheme or "").lower()
    if scheme == "rediss":
        from redis.connection import SSLConnection
        cert_str = qs.get("ssl_cert_reqs", [os.getenv("REDIS_SSL_CERT_REQS", "required")])[0]
        kwargs.update(
            connection_class=SSLConnection,
            ssl_cert_reqs=_map_cert(cert_str),
        )
    else:
        from redis.connection import Connection
        kwargs.update(connection_class=Connection)

    # חשוב: לא מעבירים ssl=True ידנית; נותנים ל-class לטפל בזה.
    cli = redis.from_url(url, **kwargs)
    return cli


def ping_safe() -> bool:
    try:
        r = make_client()
        return bool(r.ping())
    except Exception as e:
        _LOG.warning({"event": "redis.ping_failed", "error": str(e)})
        return False









