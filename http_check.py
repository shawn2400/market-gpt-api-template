#!/usr/bin/env python3
# http_check.py
from __future__ import annotations
import sys, http.client
from urllib.parse import urlparse

BASE_URL = (sys.argv[1] if len(sys.argv) > 1 else "https://algogpt-prod.onrender.com").rstrip("/")
u = urlparse(BASE_URL)
conn_cls = http.client.HTTPSConnection if u.scheme == "https" else http.client.HTTPConnection
conn = conn_cls(u.netloc, timeout=12)

for path in ("/readyz", "/ops/manager/health"):
    try:
        conn.request("GET", path)
        r = conn.getresponse()
        body = r.read().decode("utf-8","ignore")
        print(f"{path} -> {r.status}\n{body}\n{'-'*50}")
    except Exception as e:
        print(f"{path} -> ERROR: {e}")
conn.close()
