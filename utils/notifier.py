# FILE: utils/notifier.py
from __future__ import annotations
import asyncio
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Any, Dict, List, Optional, Tuple

from .timehelpers import now_ts

TZ_IL = ZoneInfo("Asia/Jerusalem")

@dataclass
class NotifierConfig:
    cadence_hours: int = 3
    daily_cap: int = 5
    immediate_kinds: Tuple[str, ...] = ("approval","emergency")
    always_send_kinds: Tuple[str, ...] = ("eod",)
    coalesce: bool = True
    coalesce_max_items: int = 50

def _html(s: str) -> str:
    return s.replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")

class Notifier:
    """
    Coalesces non-urgent messages into a periodic digest,
    enforces a per-day cap, while sending approvals/emergencies immediately.
    """
    def __init__(self, policy, session, send_telegram_func):
        n = policy.gate("NOTIFY", {}) or {}
        self.cfg = NotifierConfig(
            cadence_hours = int(n.get("cadence_hours", 3)),
            daily_cap = int(n.get("daily_cap", 5)),
            immediate_kinds = tuple(n.get("immediate_kinds", ["approval","emergency"])),
            always_send_kinds = tuple(n.get("always_send_kinds", ["eod"])),
            coalesce = bool(n.get("coalesce", True)),
            coalesce_max_items = int(n.get("coalesce_max_items", 50)),
        )
        self.session = session
        self._send_telegram = send_telegram_func
        self.buffer: List[Tuple[str,str]] = []  # (kind, text)
        self.sent_today: int = 0
        self._last_date = datetime.now(TZ_IL).date()
        self._lock = asyncio.Lock()

    async def _reset_if_new_day(self):
        today = datetime.now(TZ_IL).date()
        if today != self._last_date:
            self._last_date = today
            self.sent_today = 0

    async def send(self, kind: str, text: str, urgent: bool = False, keyboard: Optional[Dict[str, Any]] = None) -> bool:
        await self._reset_if_new_day()

        if urgent or (kind in self.cfg.immediate_kinds) or (kind in self.cfg.always_send_kinds):
            await self._send(kind, text, keyboard)
            return True

        if not self.cfg.coalesce:
            if self.sent_today >= self.cfg.daily_cap:
                return False
            await self._send(kind, text, keyboard)
            return True

        # coalesce path
        async with self._lock:
            if len(self.buffer) < self.cfg.coalesce_max_items:
                self.buffer.append((kind, text))
        return False

    async def _send(self, kind: str, text: str, keyboard: Optional[Dict[str, Any]]):
        # always_send_kinds are not counted towards the cap
        countable = kind not in self.cfg.always_send_kinds
        if countable and (kind not in self.cfg.immediate_kinds):
            await self._reset_if_new_day()
            if self.sent_today >= self.cfg.daily_cap:
                return

        await self._send_telegram(self.session, text, keyboard)

        if countable and (kind not in self.cfg.immediate_kinds):
            self.sent_today += 1

    async def flush_digest(self):
        await self._reset_if_new_day()
        async with self._lock:
            items = self.buffer[:]
            self.buffer.clear()

        if not items:
            return

        ts_il, ts_utc = now_ts("%d/%m/%Y %H:%M:%S %Z", "%Y-%m-%d %H:%M:%S UTC")
        lines = [f"🧩 דיג'סט התראות מצטבר\n<b>זמן:</b> {ts_il} | <b>Time:</b> {ts_utc}"]
        for i, (_, txt) in enumerate(items[:20], start=1):
            lines.append(f"{i}. {txt}")
        if len(items) > 20:
            lines.append(f"… ועוד {len(items)-20} פריטים")

        await self._send("digest", "\n".join(lines), keyboard=None)

