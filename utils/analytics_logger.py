# utils/analytics_logger.py
# =========================
# תפקיד: תיעוד אנליטי של פעולות אישור/דחייה / ביצועים / שינויים במערכת
from __future__ import annotations

import os
import io
import json
import logging
import time
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, Any, List

logger = logging.getLogger("algogpt.analytics")

# ─────────────────────────── קונפיג ───────────────────────────
ANALYTICS_DIR = Path(os.getenv("ANALYTICS_DIR", "logs/analytics"))
ANALYTICS_DIR.mkdir(parents=True, exist_ok=True)

APPROVALS_FILE = ANALYTICS_DIR / os.getenv("APPROVALS_JSONL", "approvals_log.jsonl")
R_HISTORY_FILE = ANALYTICS_DIR / os.getenv("R_HISTORY_JSONL", "r_history.jsonl")

R_HIST_MAX_FILE = int(os.getenv("R_HIST_MAX_FILE", "5000"))   # שמירה מקומית של עד N שורות
R_HIST_WINDOW_DEFAULT = int(os.getenv("R_HIST_WINDOW_DEFAULT", "50"))

# Redis אופציונלי
try:
    import redis  # type: ignore
except Exception:
    redis = None  # type: ignore

NS = os.getenv("REDIS_NAMESPACE", "algogpt")
REDIS_URL = os.getenv("REDIS_URL", "").strip()

def _r():
    if not (redis and REDIS_URL):
        return None
    try:
        return redis.Redis.from_url(REDIS_URL, decode_responses=True)
    except Exception as e:
        logger.debug("analytics._r failed: %s", e)
        return None

# ─────────────────────── Utilities מקומיים ───────────────────────
def _append_jsonl(path: Path, obj: Dict[str, Any]) -> None:
    try:
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(obj, ensure_ascii=False, separators=(",", ":")) + "\n")
    except Exception as e:
        logger.warning("[analytics] failed to append jsonl (%s): %s", path, e)

def _file_line_count(path: Path) -> int:
    try:
        with path.open("rb") as f:
            return sum(1 for _ in f)
    except Exception:
        return 0

def _truncate_head_keep_last(path: Path, keep_last: int) -> None:
    """
    שומר רק את keep_last השורות האחרונות בקובץ JSONL (יעיל מספיק ל־N~אלפים).
    """
    try:
        if not path.exists():
            return
        with path.open("r", encoding="utf-8") as f:
            lines = f.readlines()
        if len(lines) <= keep_last:
            return
        with path.open("w", encoding="utf-8") as f:
            f.writelines(lines[-keep_last:])
    except Exception as e:
        logger.debug("truncate_head_keep_last failed: %s", e)

def _tail_jsonl(path: Path, n: int) -> List[Dict[str, Any]]:
    n = max(1, int(n))
    try:
        if not path.exists():
            return []
        with path.open("rb") as f:
            # קריאת זנב יעילה (blocks לא גדולים)
            block_size = 4096
            data = b""
            f.seek(0, io.SEEK_END)
            pos = f.tell()
            while pos > 0 and data.count(b"\n") <= n:
                read_size = min(block_size, pos)
                pos -= read_size
                f.seek(pos, io.SEEK_SET)
                data = f.read(read_size) + data
            text = data.decode("utf-8", errors="ignore")
        lines = [ln for ln in text.splitlines() if ln.strip()]
        tail = lines[-n:]
        out: List[Dict[str, Any]] = []
        for ln in tail:
            try:
                out.append(json.loads(ln))
            except Exception:
                continue
        return out
    except Exception as e:
        logger.debug("tail_jsonl failed (%s): %s", path, e)
        return []

# ────────────────────────── אישורים/דחיות ──────────────────────────
def log_approval_event(
    trade_id: str,
    symbol: str,
    action: str,     # "approve" / "reject"
    reason: Optional[str] = None,
    user_id: Optional[int] = None,
    metadata: Optional[dict] = None
) -> None:
    """
    רושם אירוע אישור/דחייה לקובץ JSONL. לא מפיל את הזרימה אם יש כשל.
    """
    try:
        event = {
            "ts": datetime.utcnow().isoformat(timespec="seconds") + "Z",
            "trade_id": str(trade_id),
            "symbol": (symbol or "").upper(),
            "action": str(action or "").lower(),
            "reason": reason,
            "user_id": user_id,
            "metadata": metadata or {},
        }
        _append_jsonl(APPROVALS_FILE, event)
    except Exception as e:
        logger.warning("[analytics] failed to log approval event: %s", e)

# ─────────────────────────── ביצועים (R) ───────────────────────────
def record_trade_outcome_R(symbol: str, R: float) -> None:
    """
    שומר תוצאת טרייד ביחידות R גם ב־Redis (אם יש) וגם מקומית (JSONL),
    עם cap על אורך ההיסטוריה המקומית.
    """
    sym = (symbol or "").upper()
    try:
        Rf = float(R)
    except Exception:
        Rf = 0.0

    # Redis list
    r = _r()
    if r:
        try:
            rec = {"ts": time.time(), "symbol": sym, "R": Rf}
            key = f"{NS}:analytics:R_hist"
            r.lpush(key, json.dumps(rec, ensure_ascii=False, separators=(",", ":")))
            r.ltrim(key, 0, int(os.getenv("R_HIST_MAX", "5000")) - 1)
        except Exception as e:
            logger.debug("record_trade_outcome_R redis failed: %s", e)

    # Local JSONL
    _append_jsonl(R_HISTORY_FILE, {
        "ts": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "symbol": sym,
        "R": Rf,
    })
    # שמירה על גודל הקובץ סביר
    try:
        if _file_line_count(R_HISTORY_FILE) > R_HIST_MAX_FILE:
            _truncate_head_keep_last(R_HISTORY_FILE, R_HIST_MAX_FILE)
    except Exception:
        pass

def get_expectancy_rolling(window_n: int = R_HIST_WINDOW_DEFAULT) -> float:
    """
    מחזיר Expectancy (ממוצע R) על חלון אחרון. אם יש Redis – יעדיף אותו;
    אחרת יקרא מה־JSONL המקומי (זנב N).
    """
    n = max(1, int(window_n))

    # Redis
    r = _r()
    if r:
        try:
            raw = r.lrange(f"{NS}:analytics:R_hist", 0, n - 1)
            vals: List[float] = []
            for x in raw:
                try:
                    obj = json.loads(x)
                    vals.append(float(obj.get("R", 0.0)))
                except Exception:
                    continue
            return float(sum(vals) / len(vals)) if vals else 0.0
        except Exception as e:
            logger.debug("get_expectancy_rolling redis failed: %s", e)

    # Local JSONL
    tail = _tail_jsonl(R_HISTORY_FILE, n)
    vals2: List[float] = []
    for obj in tail:
        try:
            vals2.append(float(obj.get("R", 0.0)))
        except Exception:
            continue
    return float(sum(vals2) / len(vals2)) if vals2 else 0.0

__all__ = [
    "log_approval_event",
    "record_trade_outcome_R",
    "get_expectancy_rolling",
]


