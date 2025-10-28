# -*- coding: utf-8 -*-
from __future__ import annotations

# Placeholder anti_replay (real code will be added in a follow-up commit through the PR discussion).
# This file ensures imports won't break while we wire the full signing gate in main.py.

from typing import Any, Dict, Optional, Tuple


def verify_request(ts_header: Optional[str], nonce_header: Optional[str], signature_header: Optional[str],
                   route: str, body: Any, *, require_signature: bool = False, http_method: str = "POST",
                   host_header: str = "", date_header: str = "", key_lookup: Optional[Dict[str, str]] = None,
                   ts_skew_sec: int = 90, enforce_host: bool = True) -> Tuple[bool, str]:
    if not require_signature:
        return True, "ok (signature not required)"
    # Minimal permissive fallback; the full HMAC/nonce/timestamp verification will be added in the PR diff.
    return True, "ok (permissive placeholder)"
