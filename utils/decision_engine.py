# utils/decision_log.py
from __future__ import annotations
import logging, uuid
from typing import Optional, Dict, Any

logger = logging.getLogger("algogpt.decision")

def _id(x: Optional[str]) -> str:
    return x or uuid.uuid4().hex[:12]

def log_decision(
    *, event: str, symbol: str, side: Optional[str] = None,
    reason_code: Optional[str] = None, setup_type: Optional[str] = None,
    request_id: Optional[str] = None, action_id: Optional[str] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> None:
    payload = {
        "event": event,
        "symbol": (symbol or "").upper(),
        "side": (side or "").upper() if side else None,
        "reason_code": reason_code,
        "setup_type": setup_type,
        "request_id": _id(request_id),
        "action_id": _id(action_id),
    }
    if extra:
        payload.update({"extra": extra})
    logger.info(payload)

__all__ = ["log_decision"]








