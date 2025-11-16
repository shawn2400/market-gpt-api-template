# -*- coding: utf-8 -*-
"""
Neon Auto-Resume Module
Automatically resumes Neon PostgreSQL endpoint via API if it's paused
"""
from __future__ import annotations
import os
import time
import json
import urllib.request
import urllib.error
import logging

logger = logging.getLogger(__name__)

NEON_API_KEY = os.getenv("NEON_API_KEY", "")
NEON_PROJECT_ID = os.getenv("NEON_PROJECT_ID", "")
NEON_ENDPOINT_ID = os.getenv("NEON_ENDPOINT_ID", "")
NEON_BASE = "https://console.neon.tech/api/v2"


def resume_endpoint(timeout_sec: int = 30) -> tuple[bool, str]:
    """
    Resume Neon endpoint via API
    Returns: (success: bool, message: str)
    """
    if not (NEON_API_KEY and NEON_PROJECT_ID and NEON_ENDPOINT_ID):
        return False, "NEON vars missing (NEON_API_KEY/NEON_PROJECT_ID/NEON_ENDPOINT_ID)"
    
    url = f"{NEON_BASE}/projects/{NEON_PROJECT_ID}/endpoints/{NEON_ENDPOINT_ID}/start"
    
    try:
        req = urllib.request.Request(
            url,
            method="POST",
            headers={
                "Authorization": f"Bearer {NEON_API_KEY}",
                "Content-Type": "application/json"
            }
        )
        
        with urllib.request.urlopen(req, timeout=timeout_sec) as response:
            _ = response.read()
            logger.info(f"Neon endpoint resumed successfully")
            return True, "Neon endpoint resume requested"
            
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8", "ignore") if hasattr(e, 'read') else str(e)
        return False, f"HTTP {e.code}: {error_body}"
    except Exception as e:
        logger.exception(f"Neon resume failed: {e}")
        return False, f"Neon resume failed: {e!r}"


def ensure_neon_running(wait_sec: int = 3) -> dict:
    """
    Ensure Neon endpoint is running (resume if needed)
    Returns: {"ok": bool, "message": str}
    """
    success, message = resume_endpoint()
    
    if success and wait_sec > 0:
        # Give the endpoint time to start
        time.sleep(wait_sec)
    
    return {"ok": success, "message": message}
