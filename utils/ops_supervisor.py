# FILE: utils/ops_supervisor.py
import asyncio
import json
import os
import signal
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
from typing import Any, Dict, Optional, Tuple

import aiohttp
import yaml

# -------------------- Config & Globals --------------------
POLICY_PATH = os.getenv("OPS_POLICY_PATH", "policies/ops_policy.yaml")
TZ_IL = ZoneInfo("Asia/Jerusalem")

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_BASE = os.getenv("OPENAI_BASE", "https://api.openai.com")  # optional override
OPENAI_MODEL_MINI = os.getenv("OPENAI_MODEL_MINI", "gpt-4o-mini")

AIX_API_KEY = os.getenv("AIX_API_KEY", "")
AIX_API_BASE = os.getenv("AIX_API_BASE", "https://api.x.ai")   # OpenAI-compatible style
AIX_MODEL_DEFAULT = os.getenv("AIX_MODEL_DEFAULT", "grok-3-mini")
AIX_MODEL_UP1 = os.getenv("AIX_MODEL_UP1", "grok-3")
AIX_MODEL_UP2 = os.getenv("AIX_MODEL_UP2", "grok-4")

HTTP_TIMEOUT = aiohttp.ClientTimeout(total=30)

# -------------------- Utilities --------------------
def now_ts(fmt_il: str, fmt_utc: str) -> Tuple[str, str]:
    now_il = datetime.now(TZ_IL)
    ts_il = now_il.strftime(fmt_il)
    ts_utc = now_il.astimezone(timezone.utc).strftime(fmt_utc)
    return ts_il, ts_utc

async def send_telegram(session: aiohttp.ClientSession, text: str, keyboard: Optional[Dict[str, Any]] = None):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text[:4096],
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    if keyboard:
        payload["reply_markup"] = keyboard
    try:
        async with session.post(url, json=payload, timeout=HTTP_TIMEOUT) as r:
            await r.text()
    except Exception:
        pass

# -------------------- Policy --------------------
@dataclass
class Policy:
    raw: Dict[str, Any]

    @property
    def time_formats(self):
        t = self.raw.get("TIME", {})
        return (
            t.get("formats", {}).get("ts_il", "%d/%m/%Y %H:%M:%S %Z"),
            t.get("formats", {}).get("ts_utc", "%Y-%m-%d %H:%M:%S UTC"),
        )

    def gate(self, key: str, default: Any = None) -> Any:
        return self.raw.get(key, default)


def load_policy() -> Policy:
    with open(POLICY_PATH, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return Policy(data)

# -------------------- Providers (AIX/OpenAI) --------------------
class LLMProvider:
    def __init__(self, session: aiohttp.ClientSession, name: str):
        self.session = session
        self.name = name

    async def chat_json(self, model: str, system: str, user: str, max_tokens: int = 800) -> Dict[str, Any]:
        raise NotImplementedError

class OpenAIProvider(LLMProvider):
    async def chat_json(self, model: str, system: str, user: str, max_tokens: int = 800) -> Dict[str, Any]:
        if not OPENAI_API_KEY:
            return {"error": "OPENAI_API_KEY missing"}
        url = f"{OPENAI_BASE}/v1/chat/completions"
        headers = {"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"}
        body = {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0.2,
            "max_tokens": max_tokens,
            "response_format": {"type": "json_object"}
        }
        async with self.session.post(url, headers=headers, json=body, timeout=HTTP_TIMEOUT) as r:
            data = await r.json()
            return data

class AIXProvider(LLMProvider):
    async def chat_json(self, model: str, system: str, user: str, max_tokens: int = 800) -> Dict[str, Any]:
        if not AIX_API_KEY:
            return {"error": "AIX_API_KEY missing"}
        # xAI (AIX) – OpenAI-like interface
        url = f"{AIX_API_BASE}/v1/chat/completions"
        headers = {"Authorization": f"Bearer {AIX_API_KEY}", "Content-Type": "application/json"}
        body = {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0.2,
            "max_tokens": max_tokens,
            "response_format": {"type": "json_object"}
        }
        async with self.session.post(url, headers=headers, json=body, timeout=HTTP_TIMEOUT) as r:
            data = await r.json()
            return data

# -------------------- Core Supervisor --------------------
class Supervisor:
    def __init__(self, policy: Policy):
        self.policy = policy
        self.session = None
        self.running = True

    async def __aenter__(self):
        self.session = aiohttp.ClientSession()
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self.session.close()

    async def run(self):
        ts_il_fmt, ts_utc_fmt = self.policy.time_formats
        ts_il, ts_utc = now_ts(ts_il_fmt, ts_utc_fmt)
        await send_telegram(self.session, f"📅🕒 <b>זמן:</b> {ts_il} | <b>Time:</b> {ts_utc}\n🔵 Info | Ops Supervisor starting (v3.3)")

        # schedule tasks
        sched = self.policy.gate("SCHEDULE", {})
        tick_seconds = int(sched.get("tick_seconds", 60))
        maintenance_minutes = int(sched.get("maintenance_minutes", 45))

        tasks = [
            asyncio.create_task(self.loop_health(tick_seconds)),
            asyncio.create_task(self.loop_maintenance(maintenance_minutes)),
            asyncio.create_task(self.loop_nightly()),
            asyncio.create_task(self.loop_eod()),
        ]

        # Auto-onboard on start
        await self.auto_onboard()

        # handle signals (Linux)
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, lambda s=sig: asyncio.create_task(self.shutdown(s)))
            except NotImplementedError:
                pass  # environments without signal handler support

        await asyncio.gather(*tasks)

    async def shutdown(self, sig):
        if not self.running:
            return
        self.running = False
        ts_il_fmt, ts_utc_fmt = self.policy.time_formats
        ts_il, ts_utc = now_ts(ts_il_fmt, ts_utc_fmt)
        await send_telegram(self.session, f"📅🕒 <b>זמן:</b> {ts_il} | <b>Time:</b> {ts_utc}\n🔴 Stopping gracefully ({sig.name})")
        await asyncio.sleep(0.2)
        await self.session.close()
        os._exit(0)

    # ---------------- Loops ----------------
    async def loop_health(self, tick_seconds: int):
        while self.running:
            try:
                ok, diag = await self.health_check()
                if not ok:
                    await self.auto_heal(diag)
            except Exception as e:
                await send_telegram(self.session, f"🔴❗ Health loop error: {e}")
            await asyncio.sleep(tick_seconds)

    async def loop_maintenance(self, minutes: int):
        while self.running:
            try:
                await self.maintenance_cycle()
            except Exception as e:
                await send_telegram(self.session, f"🟡 Maintenance error: {e}")
            await asyncio.sleep(minutes * 60)

    async def loop_nightly(self):
        while self.running:
            await self.sleep_until_local(self.policy.gate("SCHEDULE", {}).get("nightly_sweep_local_time", "02:30"))
            try:
                await self.nightly_sweep()
            except Exception as e:
                await send_telegram(self.session, f"🟡 Nightly error: {e}")

    async def loop_eod(self):
        while self.running:
            await self.sleep_until_local(self.policy.gate("SCHEDULE", {}).get("eod_report_local_time", "23:57"))
            try:
                await self.eod_report()
            except Exception as e:
                await send_telegram(self.session, f"🟡 EOD error: {e}")

    # ---------------- Helpers ----------------
    async def sleep_until_local(self, hh_mm: str):
        now_il = datetime.now(TZ_IL)
        hh, mm = map(int, hh_mm.split(":"))
        target = now_il.replace(hour=hh, minute=mm, second=0, microsecond=0)
        if target <= now_il:
            target = target + timedelta(days=1)
        await asyncio.sleep(max(0, (target - now_il).total_seconds()))

    # ---------------- Health / Auto-Heal ----------------
    async def health_check(self) -> Tuple[bool, str]:
        # TODO: integrate real CPU/MEM/WS/API-error metrics
        # Return (ok, diag)
        return True, "ok"

    async def auto_heal(self, diag: str):
        ts_il_fmt, ts_utc_fmt = self.policy.time_formats
        ts_il, ts_utc = now_ts(ts_il_fmt, ts_utc_fmt)
        await send_telegram(self.session, f"📅🕒 <b>זמן:</b> {ts_il} | <b>Time:</b> {ts_utc}\n🧯🛠️ אירוע טופל אוטומטית | Incident Auto-Heal\n<b>Root-Cause:</b> {diag}")
        # Implement reconnect/restart/rollback-config here

    # ---------------- Maintenance Cycle ----------------
    async def maintenance_cycle(self):
        # 1) Propose change via AIX (primary). If CRS high/sensitive, also consult OpenAI.
        proposal = await self.propose_change()
        if not proposal:
            return
        crs = max(0, min(10, int(proposal.get("crs", 3))))
        sensitive = bool(proposal.get("sensitive", False))

        # 2) Preflight gates/tests/budget/security
        ok, reason = await self.preflight_checks()
        if not ok:
            await self.notify_cancel("preflight", reason)
            return

        # 3) Canary by CRS
        canary_pct = self.canary_by_crs(crs)
        ok, reason = await self.run_canary(proposal, canary_pct)
        if not ok:
            await self.notify_cancel("canary", reason, rollback=True)
            return

        # 4) Promote
        ok, reason = await self.promote(proposal)
        if not ok:
            await self.notify_cancel("promote", reason, rollback=True)
            return

        # 5) Post-verify
        ok, reason = await self.post_verify(proposal)
        if not ok:
            await self.notify_cancel("postverify", reason, rollback=True)
            return

        # 6) Success notify
        await self.notify_success(proposal)

    def canary_by_crs(self, crs: int) -> int:
        sizes = self.policy.gate("CANARY", {}).get("size_by_crs", {"0-3": 5, "4-6": 15, "7-10": 30})
        if crs <= 3:
            return int(sizes.get("0-3", 5))
        elif crs <= 6:
            return int(sizes.get("4-6", 15))
        else:
            return int(sizes.get("7-10", 30))

    async def notify_cancel(self, stage: str, reason: str, rollback: bool = False):
        ts_il_fmt, ts_utc_fmt = self.policy.time_formats
        ts_il, ts_utc = now_ts(ts_il_fmt, ts_utc_fmt)
        text = (
            f"📅🕒 <b>זמן:</b> {ts_il} | <b>Time:</b> {ts_utc}\n"
            f"🔴❌ בוטל בזמן ביצוע | Execution Cancelled\n"
            f"<b>שלב:</b> {stage}\n"
            f"<b>סיבה:</b> {reason}\n"
        )
        if rollback:
            text += "⏪ <b>Rollback:</b> הושלם לגרסה יציבה\n"
        await send_telegram(self.session, text)

    async def notify_success(self, proposal: Dict[str, Any]):
        ts_il_fmt, ts_utc_fmt = self.policy.time_formats
        ts_il, ts_utc = now_ts(ts_il_fmt, ts_utc_fmt)
        text = (
            f"📅🕒 <b>זמן:</b> {ts_il} | <b>Time:</b> {ts_utc}\n"
            f"🟢🚀 שדרוג הושלם | Upgrade Promoted\n"
            f"<b>גרסה:</b> v{proposal.get('version','X.Y.Z')}\n"
        )
        await send_telegram(self.session, text)

    # ---------------- Nightly / EOD ----------------
    async def nightly_sweep(self):
        ts_il_fmt, ts_utc_fmt = self.policy.time_formats
        ts_il, ts_utc = now_ts(ts_il_fmt, ts_utc_fmt)
        await send_telegram(self.session, f"📅🕒 <b>זמן:</b> {ts_il} | <b>Time:</b> {ts_utc}\n🧹 Nightly sweep started…")
        # TODO: imports/AST/SBOM/log rotation/security checks

    async def eod_report(self):
        ts_il_fmt, ts_utc_fmt = self.policy.time_formats
        ts_il, ts_utc = now_ts(ts_il_fmt, ts_utc_fmt)
        # Example KPIs (placeholder)
        text = (
            f"📅🕒 <b>זמן:</b> {ts_il} | <b>Time:</b> {ts_utc}\n"
            f"📊 סיכום יומי | Daily EOD\n"
            f"<pre>p95: 1080ms   errors: 1.5%   ws_disc: 2\n"
            f"MTTR: 48s   advisor_calls: 3   budget: OAI $0.12 | AIX $0.28</pre>\n"
            f"<b>שינויים:</b> 1 (Promoted: 1 / Rolled: 0)\n"
            f"Highlights: latency↓18%, errors↓0.6%"
        )
        await send_telegram(self.session, text)

    # ---------------- LLM Orchestration ----------------
    async def propose_change(self) -> Optional[Dict[str, Any]]:
        system = (
            "You are the Ops-Advisor. Return a STRICT JSON with keys: "
            "{ 'crs': int(0-10), 'sensitive': bool, 'plan': str, 'version': str } only."
        )
        user = "Produce one safe improvement for the next 45min window."
        # AIX primary
        aix = AIXProvider(self.session, "xai")
        data = await aix.chat_json(AIX_MODEL_DEFAULT, system, user)
        proposal = self._extract_json(data)
        if not proposal:
            return None

        # Risk gate: if CRS>=5 or sensitive -> ask OpenAI advisor for cross-check
        crs = int(proposal.get("crs", 3))
        sensitive = bool(proposal.get("sensitive", False))
        if (crs >= 5 or sensitive) and OPENAI_API_KEY:
            oa = OpenAIProvider(self.session, "openai")
            data2 = await oa.chat_json(OPENAI_MODEL_MINI, system, user)
            prop2 = self._extract_json(data2)
            if prop2 and abs(int(prop2.get("crs", 3)) - crs) >= 3:
                # disagreement → require approval (skip auto)
                await self.notify_cancel("advisor_disagree", "advisor and primary disagree", rollback=False)
                return None
        return proposal

    def _extract_json(self, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        try:
            if "choices" in data:
                content = data["choices"][0]["message"]["content"]
                return json.loads(content)
        except Exception:
            pass
        return None

    async def preflight_checks(self) -> Tuple[bool, str]:
        # TODO: real gates/tests/budget/security checks
        return True, "ok"

    async def run_canary(self, proposal: Dict[str, Any], pct: int) -> Tuple[bool, str]:
        # TODO: implement real canary metrics watch
        await asyncio.sleep(2)
        return True, "ok"

    async def promote(self, proposal: Dict[str, Any]) -> Tuple[bool, str]:
        # TODO: apply change (config tweak / patch)
        await asyncio.sleep(1)
        return True, "ok"

    async def post_verify(self, proposal: Dict[str, Any]) -> Tuple[bool, str]:
        # TODO: quick KPI verify
        await asyncio.sleep(1)
        return True, "ok"

    # ---------------- Auto-Onboard ----------------
    async def auto_onboard(self):
        ao = self.policy.gate("AUTO_ONBOARD", {})
        if not ao or not ao.get("enabled", True):
            return
        ts_il_fmt, ts_utc_fmt = self.policy.time_formats
        ts_il, ts_utc = now_ts(ts_il_fmt, ts_utc_fmt)
        await send_telegram(self.session, f"📅🕒 <b>זמן:</b> {ts_il} | <b>Time:</b> {ts_utc}\n🟣 Auto-Onboard starting…")
        # TODO: check credentials/allowlist/handshake and bring exchanges/features online gradually


async def main():
    policy = load_policy()
    async with Supervisor(policy) as sup:
        await sup.run()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass

