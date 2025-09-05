# utils/analytics_logger.py
# =========================
# תפקיד: תיעוד אנליטי של פעולות אישור/דחייה / ביצועים / שינויים במערכת

import os
import json
import logging
from pathlib import Path
from datetime import datetime
from typing import Optional

ANALYTICS_DIR = Path("logs/analytics")
ANALYTICS_FILE = ANALYTICS_DIR / "approvals_log.jsonl"

logger = logging.getLogger("algogpt.analytics")

# ודא שהתקייה קיימת מראש
ANALYTICS_DIR.mkdir(parents=True, exist_ok=True)

def log_approval_event(
    trade_id: str,
    symbol: str,
    action: str,     # "approve" / "reject"
    reason: Optional[str] = None,
    user_id: Optional[int] = None,
    metadata: Optional[dict] = None
) -> None:
    try:
        event = {
            "ts": datetime.utcnow().isoformat(),
            "trade_id": trade_id,
            "symbol": symbol.upper(),
            "action": action.lower(),
            "reason": reason,
            "user_id": user_id,
            "metadata": metadata or {},
        }
        with open(ANALYTICS_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")
    except Exception as e:
        logger.warning("[analytics] failed to log approval event: %s", e)

