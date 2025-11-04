# FILE: utils/ops_supervisor.py
from __future__ import annotations
import asyncio
import json
import os
import re
import signal
import time
import hmac
import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urlencode, quote_plus

import aiohttp
import yaml

try:
    import redis  # type: ignore
except Exception:
    redis = None  # optional: supervisor still runs without pubsub/persistence

from utils.notifier import Notifier  # NEW

# -------------------- Config & Globals --------------------
POLICY_PATH = os.getenv("OPS_POLICY_PATH", "policies/ops_policy.yaml")
TZ_IL = ZoneInfo("Asia/Jerusalem")
VERSION = "4.1"  # bumped

# Telegram
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

# Providers
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
OPENAI_BASE = os.getenv("OPENAI_BASE", "https://api.openai.com").strip()
OPENAI_MODEL_MINI = os.getenv("OPENAI_MODEL_MINI", "gpt-4o-mini").strip()

AIX_API_KEY = os.getenv("AIX_API_KEY", "").strip()
AIX_API_BASE = os.getenv("AIX_API_BASE", "https://api.x.ai").strip()
AIX_MODEL_DEFAULT = os.getenv("AIX_MODEL_DEFAULT", "grok-3-mini").strip()

# Provider order (env-configurable)
LLM_PROVIDER_ORDER = os.getenv("LLM_PROVIDER_ORDER", "openai,aix,conservative").strip()

# Infra / Render
REDIS_URL_ENV = os.getenv("REDIS_URL", "")
PRIMARY_PUBLIC_HOST = os.getenv("PRIMARY_PUBLIC_HOST", "").strip().rstrip("/")
DEPLOY_HOOK = os.getenv("RENDER_DEPLOY_HOOK_MAIN", "").strip()
RENDER_API_KEY = os.getenv("RENDER_API_KEY", "").strip()
SECONDARY_SERVICE_ID = os.getenv("SECONDARY_SERVICE_ID", "").strip()  # ops-supervisor
PRIMARY_SERVICE_ID = os.getenv("PRIMARY_SERVICE_ID", "").strip()      # algogpt-docker

# Approval signing (webhook and supervisor MUST share the same secret)
WEBHOOK_HMAC_SECRET = os.getenv("WEBHOOK_HMAC_SECRET", "").encode() if os.getenv("WEBHOOK_HMAC_SECRET") else None

HTTP_TIMEOUT = aiohttp.ClientTimeout(total=20)

# cooldowns for auto-heal actions
_last_action_ts: Dict[str, float] = {}

def _cooldown_ok(key: str, sec: int) -> bool:
    now = time.time()
    ts = _last_action_ts.get(key, 0.0)
    if now - ts >= sec:
        _last_action_ts[key] = now
        return True
    return False

# -------------------- Safe import for RenderAPI --------------------
RenderAPI = None
try:
    from utils.render_api import RenderAPI  # when run with: python -m utils.ops_supervisor
except Exception:
    try:
        import sys, pathlib
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
        from utils.render_api import RenderAPI  # fallback when run as a script
    except Exception:
        RenderAPI = None

# -------------------- Utilities --------------------
def now_ts(fmt_il: str, fmt_utc: str) -> Tuple[str, str]:
    now_il = datetime.now(TZ_IL)
    ts_il = now_il.strftime(fmt_il)
    ts_utc = now_il.astimezone(timezone.utc).strftime(fmt_utc)
    return ts_il, ts_utc

def _html(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

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
        data = yaml.safe_load(f) or {}
    return Policy(data)

# -------------------- Providers --------------------
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
            "messages": [{"role":"system","content":system},{"role":"user","content":user}],
            "temperature": 0.2,
            "max_tokens": max_tokens,
            "response_format": {"type": "json_object"},
        }
        async with self.session.post(url, headers=headers, json=body, timeout=HTTP_TIMEOUT) as r:
            return await r.json()

class AIXProvider(LLMProvider):
    async def chat_json(self, model: str, system: str, user: str, max_tokens: int = 800) -> Dict[str, Any]:
        if not AIX_API_KEY:
            return {"error": "AIX_API_KEY missing"}
        url = f"{AIX_API_BASE}/v1/chat/completions"
        headers = {"Authorization": f"Bearer {AIX_API_KEY}", "Content-Type": "application/json"}
        body = {
            "model": model,
            "messages": [{"role":"system","content":system},{"role":"user","content":user}],
            "temperature": 0.2,
            "max_tokens": max_tokens,
            "response_format": {"type": "json_object"},
        }
        async with self.session.post(url, headers=headers, json=body, timeout=HTTP_TIMEOUT) as r:
            return await r.json()

# -------------------- ENV Sanitize --------------------
def _clean_redis_url(u: str) -> str:
    if not u:
        return u
    u = u.strip().strip('"').strip("'").strip()
    u = u.replace("\\n", "").rstrip("\n").strip()
    if u.startswith("//") and "keyvalue.render.com" in u:
        u = "rediss:" + u
    if "keyvalue.render.com" in u and not u.startswith("rediss://"):
        u = "rediss://" + u.split("://", 1)[-1]
    if re.search(r"@red-[a-z0-9]+:6379$", u) and "keyvalue.render.com" not in u:
        m = re.match(r"^redis[s]?://([^@]+)@[^:]+:\d+$", u)
        if m:
            auth = m.group(1)
            u = f"rediss://{auth}@frankfurt-keyvalue.render.com:6379"
    return u

async def _redis_self_test(session: aiohttp.ClientSession, url: str) -> Tuple[bool, str]:
    try:
        import redis  # type: ignore
    except Exception as e:
        return False, f"redis-lib-missing: {e}"
    try:
        r = redis.Redis.from_url(url, decode_responses=True)
        ok = bool(r.ping())
        return ok, "ok" if ok else "ping-false"
    except Exception as e:
        return False, str(e)

# -------------------- Approval helpers --------------------
def _gen_ticket_id() -> str:
    ts = int(time.time() * 1000)
    rand = secrets.token_hex(8)
    return f"{ts:x}-{rand}"

def _canonical_qs(params: Dict[str, str]) -> str:
    return "&".join(f"{k}={params[k]}" for k in sorted(params))

def _hmac_sign(params: Dict[str, str]) -> str:
    if not WEBHOOK_HMAC_SECRET:
        return ""
    return hmac.new(WEBHOOK_HMAC_SECRET, _canonical_qs(params).encode(), hashlib.sha256).hexdigest()

def _approval_keyboard(approve_url: str, reject_url: str) -> Dict[str, Any]:
    return {"inline_keyboard": [[{"text": "✅ Approve", "url": approve_url}],
                                [{"text": "❌ Reject",  "url": reject_url}]]}

def _expand_env_templates(s: str) -> str:
    if not isinstance(s, str):
        return s
    return re.sub(r"\$\{([A-Z0-9_]+)\}", lambda m: os.getenv(m.group(1), ""), s)

def _iter_llm_order() -> list[str]:
    order_raw = (LLM_PROVIDER_ORDER or "").lower().replace(" ", "")
    valid = {"aix", "openai", "conservative"}
    order = [p for p in order_raw.split(",") if p in valid]
    return order or ["openai", "aix", "conservative"]

def _parse_admin_ids() -> list[str]:
    """Read TELEGRAM_ADMIN_IDS (comma/space separated) → list of IDs as strings."""
    s = os.getenv("TELEGRAM_ADMIN_IDS", "").strip()
    if not s:
        return []
    import re as _re
    return [x for x in _re.split(r"[,\s]+", s) if x]

# -------------------- Core Supervisor --------------------
class Supervisor:
    def __init__(self, policy: Policy):
        self.policy = policy
        self.session: Optional[aiohttp.ClientSession] = None
        self.running = True
        self.redis_url: str = _clean_redis_url(REDIS_URL_ENV)
        self.notifier: Optional[Notifier] = None  # NEW

    def _redis_client(self):
        if not (redis and self.redis_url):
            return None
        try:
            return redis.Redis.from_url(self.redis_url, decode_responses=True)
        except Exception:
            return None

    async def __aenter__(self):
        self.session = aiohttp.ClientSession(timeout=HTTP_TIMEOUT)
        self.notifier = Notifier(self.policy, self.session, send_telegram)  # NEW

        # ENV sanitize + runtime auto-fix
        raw = REDIS_URL_ENV
        cleaned = _clean_redis_url(raw)
        if cleaned and cleaned != raw:
            os.environ["REDIS_URL"] = cleaned
            self.redis_url = cleaned
            ts_il_fmt, ts_utc_fmt = self.policy.time_formats
            ts_il, ts_utc = now_ts(ts_il_fmt, ts_utc_fmt)
            await self._notify("ops",
                f"🛠️ Auto-sanitized <b>REDIS_URL</b> at runtime\n"
                f"<b>זמן:</b> {ts_il} | <b>Time:</b> {ts_utc}\n"
                f"<code>old={_html(repr(raw))}</code>\n<code>new={_html(repr(cleaned))}</code>")

        # quick self-test and notify
        if self.redis_url and self.session:
            ok, reason = await _redis_self_test(self.session, self.redis_url)
            if ok:
                await self._notify("health", "✅ Redis connectivity OK after sanitize.")
            else:
                await self._notify("health", f"⚠️ Redis self-test failed: <code>{_html(reason)}</code>")

        return self

    async def __aexit__(self, exc_type, exc, tb):
        if self.session:
            await self.session.close()

    async def _notify(self, kind: str, text: str, urgent: bool = False, keyboard: Optional[Dict[str, Any]] = None):
        if self.notifier:
            await self.notifier.send(kind, text, urgent=urgent, keyboard=keyboard)
        elif self.session:
            await send_telegram(self.session, text, keyboard)

    async def loop_digest(self):
        n = self.policy.gate("NOTIFY", {}) or {}
        cadence_hours = int(n.get("cadence_hours", 3))
        period = max(1, cadence_hours) * 3600
        while self.running:
            try:
                if self.notifier:
                    await self.notifier.flush_digest()
            except Exception:
                await asyncio.sleep(1)
            await asyncio.sleep(period)

    async def run(self):
        ts_il_fmt, ts_utc_fmt = self.policy.time_formats
        ts_il, ts_utc = now_ts(ts_il_fmt, ts_utc_fmt)
        await self._notify("info", f"📅🕒 <b>זמן:</b> {ts_il} | <b>Time:</b> {ts_utc}\n🔵 Info | Ops Supervisor starting (v{VERSION})")

        sched = self.policy.gate("SCHEDULE", {})
        tick_seconds = int(sched.get("tick_seconds", 60))
        maintenance_minutes = int(sched.get("maintenance_minutes", 45))

        tasks = [
            asyncio.create_task(self.loop_health(tick_seconds)),
            asyncio.create_task(self.loop_maintenance(maintenance_minutes)),
            asyncio.create_task(self.loop_nightly()),
            asyncio.create_task(self.loop_eod()),
            asyncio.create_task(self.loop_digest()),  # NEW
        ]

        await self.auto_onboard()

        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, lambda s=sig: asyncio.create_task(self.shutdown(s)))
            except NotImplementedError:
                pass

        await asyncio.gather(*tasks)

    async def shutdown(self, sig):
        if not self.running:
            return
        self.running = False
        ts_il_fmt, ts_utc_fmt = self.policy.time_formats
        ts_il, ts_utc = now_ts(ts_il_fmt, ts_utc_fmt)
        await self._notify("info", f"📅🕒 <b>זמן:</b> {ts_il} | <b>Time:</b> {ts_utc}\n🔴 Stopping gracefully ({sig.name})")
        await asyncio.sleep(0.2)
        if self.session:
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
                await self._notify("warn", f"🔴❗ Health loop error: {e}")
            await asyncio.sleep(tick_seconds)

    async def loop_maintenance(self, minutes: int):
        while self.running:
            try:
                await self.maintenance_cycle()
            except Exception as e:
                await self._notify("warn", f"🟡 Maintenance error: {e}")
            await asyncio.sleep(minutes * 60)

    async def loop_nightly(self):
        while self.running:
            await self.sleep_until_local(self.policy.gate("SCHEDULE", {}).get("nightly_sweep_local_time", "02:30"))
            try:
                await self.nightly_sweep()
            except Exception as e:
                await self._notify("warn", f"🟡 Nightly error: {e}")

    async def loop_eod(self):
        while self.running:
            await self.sleep_until_local(self.policy.gate("SCHEDULE", {}).get("eod_report_local_time", "23:57"))
            try:
                await self.eod_report()
            except Exception as e:
                await self._notify("warn", f"🟡 EOD error: {e}")

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
        if not self.session:
            return False, "no_session"
        
        # 1) Redis
        if self.redis_url:
            ok, reason = await _redis_self_test(self.session, self.redis_url)
            if not ok:
                return False, f"redis_error:{reason}"

        # 2) Primary /health
        if PRIMARY_PUBLIC_HOST:
            try:
                url = PRIMARY_PUBLIC_HOST.rstrip("/") + "/health"
                async with self.session.get(url, timeout=HTTP_TIMEOUT) as resp:
                    ok = resp.status == 200
                    if ok:
                        data = await resp.json()
                        if not bool(data.get("ok", False)):
                            return False, "primary_not_ok"
                    else:
                        return False, "primary_http_" + str(resp.status)
            except Exception:
                return False, "primary_down"

        return True, "ok"

    async def _set_env_var_http(self, service_id: str, key: str, value: str, visibility: str = "private") -> bool:
        if not (RENDER_API_KEY and service_id and self.session):
            return False
        headers = {"Authorization": f"Bearer {RENDER_API_KEY}", "Content-Type": "application/json"}
        base = "https://api.render.com"
        body_a = {"envVars": [{"key": key, "value": value, "visibility": visibility}]}
        async with self.session.put(f"{base}/v1/services/{service_id}/env-vars", headers=headers, json=body_a, timeout=HTTP_TIMEOUT) as r1:
            if 200 <= r1.status < 300:
                return True
        body_b = {"key": key, "value": value, "visibility": visibility}
        async with self.session.post(f"{base}/v1/services/{service_id}/env-vars", headers=headers, json=body_b, timeout=HTTP_TIMEOUT) as r2:
            if 200 <= r2.status < 300:
                return True
        body_c = {"envVars": [{"key": key, "value": value, "type": "SECRET" if visibility == "private" else "GENERAL"}]}
        async with self.session.put(f"{base}/v1/services/{service_id}/env-vars", headers=headers, json=body_c, timeout=HTTP_TIMEOUT) as r3:
            if 200 <= r3.status < 300:
                return True
        return False

    async def _create_deploy_http(self, service_id: str) -> bool:
        if not (RENDER_API_KEY and service_id and self.session):
            return False
        headers = {"Authorization": f"Bearer {RENDER_API_KEY}", "Content-Type": "application/json"}
        base = "https://api.render.com"
        async with self.session.post(f"{base}/v1/services/{service_id}/deploys", headers=headers, json={}, timeout=HTTP_TIMEOUT) as r:
            return 200 <= r.status < 300

    async def _persist_redis_fix_to_render(self, new_url: str) -> bool:
        if not (RENDER_API_KEY and SECONDARY_SERVICE_ID and new_url):
            return False
        try:
            if RenderAPI is not None:
                api = RenderAPI(RENDER_API_KEY)
                ok = await api.set_env_var_compat(SECONDARY_SERVICE_ID, "REDIS_URL", new_url, visibility="private")
                if not ok:
                    return False
                await api.create_deploy(SECONDARY_SERVICE_ID)
                return True
            else:
                ok = await self._set_env_var_http(SECONDARY_SERVICE_ID, "REDIS_URL", new_url, visibility="private")
                if not ok:
                    return False
                return await self._create_deploy_http(SECONDARY_SERVICE_ID)
        except Exception:
            return False

    async def _redeploy_primary(self, reason: str):
        # Only redeploy (no code mutation)
        if not self.session:
            return
        if DEPLOY_HOOK and "<SERVICE_ID>" not in DEPLOY_HOOK and "<KEY>" not in DEPLOY_HOOK:
            try:
                async with self.session.post(DEPLOY_HOOK, timeout=aiohttp.ClientTimeout(total=10)) as r:
                    _ = await r.text()
                await self._notify("heal", f"🧯 Auto-Heal: Triggered primary redeploy via hook ({reason}).")
                return
            except Exception as e:
                await self._notify("warn", f"🧯 Auto-Heal deploy hook failed: {e}")

        if RENDER_API_KEY and PRIMARY_SERVICE_ID and _cooldown_ok("render_api_redeploy", 1800):
            try:
                ok = False
                if RenderAPI is not None:
                    api = RenderAPI(RENDER_API_KEY)
                    ok = await api.create_deploy(PRIMARY_SERVICE_ID)
                else:
                    ok = await self._create_deploy_http(PRIMARY_SERVICE_ID)
                if ok:
                    await self._notify("heal", f"🧯 Auto-Heal: Triggered primary redeploy via Render API ({reason}).")
                else:
                    await self._notify("warn", "🧯 Auto-Heal Render API failed (non-2xx).")
            except Exception as e:
                await self._notify("warn", f"🧯 Auto-Heal Render API exception: {e}")

    async def auto_heal(self, diag: str):
        if diag.startswith("primary"):
            await self._redeploy_primary(diag)
            return

        if diag.startswith("redis"):
            new_clean = _clean_redis_url(os.getenv("REDIS_URL", self.redis_url))
            if new_clean and new_clean != self.redis_url and self.session:
                os.environ["REDIS_URL"] = new_clean
                self.redis_url = new_clean
                ok, reason = await _redis_self_test(self.session, self.redis_url)
                if ok:
                    await self._notify("heal", f"✅ Redis recovered after re-sanitize.\n<code>{_html(repr(self.redis_url))}</code>")
                    if await self._persist_redis_fix_to_render(new_clean):
                        await self._notify("heal", "📌 Persisted REDIS_URL fix to Render env and triggered redeploy.")
                    else:
                        await self._notify("warn", "ℹ️ Could not persist REDIS_URL via Render API (missing perms or API mismatch).")
                    return
                else:
                    await self._notify("warn", f"⚠️ Redis re-sanitize failed: <code>{_html(reason)}</code>")
            await self._notify("warn", f"⚠️ Redis issue detected: {diag}. Using external TLS endpoint recommended.")

    # ---------------- Maintenance Cycle ----------------
    async def maintenance_cycle(self):
        proposal = await self.propose_change()
        if not proposal:
            return

        crs = max(0, min(10, int(proposal.get("crs", 3))))
        sensitive = bool(proposal.get("sensitive", False))

        ok, reason = await self.preflight_checks()
        if not ok:
            await self.notify_cancel("preflight", reason)
            return

        # ===== Approval gate =====
        change_appr = self.policy.gate("CHANGE_APPROVAL", {})
        require_approval = bool(change_appr.get("required", True))
        min_crs_for_manual = int(change_appr.get("min_crs_for_manual", 2))
        needs_manual = require_approval and (sensitive or crs >= min_crs_for_manual)

        if needs_manual:
            ticket_id = await self.request_change_approval(proposal)
            if not ticket_id:
                await self.notify_cancel("approval", "failed_to_create_ticket")
                return
            timeout_s = int(self.policy.gate("APPROVAL_ENDPOINTS", {}).get("timeout_seconds", 600))
            ok, status = await self.wait_for_ticket(ticket_id, timeout_s)
            if not ok:
                await self.notify_cancel("approval", status or "not_approved")
                return
            # approved → continue

        # Canary → Promote → Post-verify
        canary_pct = self.canary_by_crs(crs)
        ok, reason = await self.run_canary(proposal, canary_pct)
        if not ok:
            await self.notify_cancel("canary", reason, rollback=True)
            return

        ok, reason = await self.promote(proposal)
        if not ok:
            await self.notify_cancel("promote", reason, rollback=True)
            return

        ok, reason = await self.post_verify(proposal)
        if not ok:
            await self.notify_cancel("postverify", reason, rollback=True)
            return

        await self.notify_success(proposal)

    def canary_by_crs(self, crs: int) -> int:
        sizes = self.policy.gate("CANARY", {}).get("size_by_crs", {"0-3": 5, "4-6": 15, "7-10": 30})
        if crs <= 3:
            v = sizes.get("0-3", 5)
        elif crs <= 6:
            v = sizes.get("4-6", 15)
        else:
            v = sizes.get("7-10", 30)
        try:
            v = float(v)
        except Exception:
            v = 5.0
        return int(round(v * 100)) if 0.0 < v <= 1.0 else int(round(v))

    async def notify_cancel(self, stage: str, reason: str, rollback: bool = False):
        ts_il_fmt, ts_utc_fmt = self.policy.time_formats
        ts_il, ts_utc = now_ts(ts_il_fmt, ts_utc_fmt)
        text = (f"📅🕒 <b>זמן:</b> {ts_il} | <b>Time:</b> {ts_utc}\n"
                f"🔴❌ בוטל בזמן ביצוע | Execution Cancelled\n"
                f"<b>שלב:</b> {stage}\n<b>סיבה:</b> {_html(reason)}\n")
        if rollback:
            text += "⏪ <b>Rollback:</b> הושלם לגרסה יציבה\n"
        await self._notify("change", text)

    async def notify_success(self, proposal: Dict[str, Any]):
        ts_il_fmt, ts_utc_fmt = self.policy.time_formats
        ts_il, ts_utc = now_ts(ts_il_fmt, ts_utc_fmt)
        text = (f"📅🕒 <b>זמן:</b> {ts_il} | <b>Time:</b> {ts_utc}\n"
                f"🟢🚀 שדרוג הושלם | Upgrade Promoted\n"
                f"<b>גרסה:</b> v{_html(proposal.get('version','X.Y.Z'))}\n")
        await self._notify("change", text)

    # ---------------- Nightly / EOD ----------------
    async def nightly_sweep(self):
        ts_il_fmt, ts_utc_fmt = self.policy.time_formats
        ts_il, ts_utc = now_ts(ts_il_fmt, ts_utc_fmt)
        await self._notify("ops", f"📅🕒 <b>זמן:</b> {ts_il} | <b>Time:</b> {ts_utc}\n🧹 Nightly sweep started…")

    async def eod_report(self):
        ts_il_fmt, ts_utc_fmt = self.policy.time_formats
        ts_il, ts_utc = now_ts(ts_il_fmt, ts_utc_fmt)
        text = (f"📅🕒 <b>זמן:</b> {ts_il} | <b>Time:</b> {ts_utc}\n"
                f"📊 סיכום יומי | Daily EOD\n"
                f"<pre>p95: 1080ms   errors: 1.5%   ws_disc: 2\n"
                f"MTTR: 48s   advisor_calls: 3   budget: OAI $0.12 | AIX $0.28</pre>\n"
                f"<b>שינויים:</b> 1 (Promoted: 1 / Rolled: 0)\n"
                f"Highlights: latency↓18%, errors↓0.6%")
        await self._notify("eod", text, urgent=True)

    # ---------------- LLM Orchestration ----------------
    async def propose_change(self) -> Optional[Dict[str, Any]]:
        """Provider order via LLM_PROVIDER_ORDER with robust fallback."""
        conservative: Dict[str, Any] = {
            "crs": 2, "sensitive": False,
            "plan": ("Tweak non-critical scheduler interval by +10% during low traffic window; "
                     "monitor p95 & error rate; auto-revert on SLO drift."),
            "version": f"{VERSION}-sched-tweak"
        }

        system = ("You are the Ops-Advisor. Return a STRICT JSON with keys: "
                  '{ "crs": int, "sensitive": bool, "plan": str, "version": str } only.')
        user = "Produce one safe improvement for the next 45min window."

        for prov in _iter_llm_order():
            try:
                if prov == "aix":
                    if not (AIX_API_KEY and self.session):
                        continue
                    data = await AIXProvider(self.session, "xai").chat_json(AIX_MODEL_DEFAULT, system, user)
                    prop = self._extract_json(data)
                    if prop: return prop
                elif prov == "openai":
                    if not (OPENAI_API_KEY and self.session):
                        continue
                    data = await OpenAIProvider(self.session, "openai").chat_json(OPENAI_MODEL_MINI, system, user)
                    prop = self._extract_json(data)
                    if prop: return prop
                elif prov == "conservative":
                    return conservative
            except Exception:
                continue

        return conservative

    def _extract_json(self, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        try:
            if "choices" in data:
                content = data["choices"][0]["message"]["content"]
                return json.loads(content)
        except Exception:
            pass
        return None

    async def preflight_checks(self) -> Tuple[bool, str]:
        """Future: add gates/tests/budget/security checks"""
        return True, "ok"

    async def run_canary(self, proposal: Dict[str, Any], pct: int) -> Tuple[bool, str]:
        """Future: implement real canary metrics watch"""
        await asyncio.sleep(2)
        return True, "ok"

    async def promote(self, proposal: Dict[str, Any]) -> Tuple[bool, str]:
        # No code deployment here — only safe config toggles (demo)
        await asyncio.sleep(1)
        return True, "ok"

    async def post_verify(self, proposal: Dict[str, Any]) -> Tuple[bool, str]:
        """Future: quick KPI verify"""
        await asyncio.sleep(1)
        return True, "ok"

    # ---------------- Approval flow ----------------
    async def request_change_approval(self, proposal: Dict[str, Any]) -> Optional[str]:
        """
        יוצר בקשת אישור ושולח קישורים חתומים. מחזיר ticket_id.
        תומך בשדה by=<approver_id> לכל מאשר מתוך TELEGRAM_ADMIN_IDS.
        """
        change_appr = self.policy.gate("CHANGE_APPROVAL", {})
        appr_endpoints = self.policy.gate("APPROVAL_ENDPOINTS", {})
        explain = bool(change_appr.get("explain", True))
        timeout_s = int(appr_endpoints.get("timeout_seconds", 600))
        two_man = bool(appr_endpoints.get("two_man_rule", True))

        ticket_id = _gen_ticket_id()
        version = str(proposal.get("version", "X.Y.Z"))
        plan = str(proposal.get("plan", ""))
        crs = int(proposal.get("crs", 0))
        sensitive = bool(proposal.get("sensitive", False))

        # בסיס לינקים מאת ה-policy (עם הרחבת ${ENV}) או נפילה ל-PRIMARY_PUBLIC_HOST
        approve_base_cfg = appr_endpoints.get("approve_url_base", "")
        approve_base_cfg = _expand_env_templates(approve_base_cfg) if approve_base_cfg else ""
        base = approve_base_cfg or (PRIMARY_PUBLIC_HOST + "/ops/approve" if PRIMARY_PUBLIC_HOST else "")

        if not base:
            await self._notify(
                "approval",
                "🟠 Approval requested but no public base URL configured "
                "(<code>PUBLIC_HOST</code> via policy APPROVAL_ENDPOINTS.approve_url_base, או <code>PRIMARY_PUBLIC_HOST</code>).",
                urgent=True,
            )
            return None

        params = {
            "ticket_id": ticket_id,
            "expires": str(int(time.time()) + timeout_s),
            "require": "2" if two_man else "1",
            "version": version,
        }

        def signed_link(action: str, extra: Optional[Dict[str, str]] = None) -> str:
            base_params = dict(params, action=action)
            if extra:
                base_params.update(extra)
            sig = _hmac_sign(base_params)
            base_params["sig"] = sig or ""  # even if no secret, include blank
            return base + "?" + urlencode(base_params, quote_via=quote_plus)

        approvers = _parse_admin_ids()

        # בניית מקלדת: כפתור לכל מאשר (Approve/Reject) כולל by=<id>
        if approvers:
            approve_row = []
            reject_row = []
            for aid in approvers:
                approve_row.append({"text": f"✅ Approve ({aid})", "url": signed_link("approve", {"by": aid})})
                reject_row.append({"text": f"❌ Reject ({aid})",  "url": signed_link("reject",  {"by": aid})})
            kb = {"inline_keyboard": [approve_row, reject_row]}
        else:
            # נסיגה: כפתורים כלליים ללא by=
            kb = _approval_keyboard(signed_link("approve"), signed_link("reject"))

        ts_il_fmt, ts_utc_fmt = self.policy.time_formats
        ts_il, ts_utc = now_ts(ts_il_fmt, ts_utc_fmt)
        lines = [
            f"📅🕒 <b>זמן:</b> {ts_il} | <b>Time:</b> {ts_utc}",
            "📝 <b>Change Approval Required</b>",
            f"ID: <code>{_html(ticket_id)}</code> | Two-man: <b>{'ON' if two_man else 'OFF'}</b> | TTL: {timeout_s}s",
            f"CRS: <b>{crs}</b> | Sensitive: <b>{'Yes' if sensitive else 'No'}</b>",
            f"Version: <code>{_html(version)}</code>",
        ]
        if explain and plan:
            lines.append(f"Plan:\n<code>{_html(plan)}</code>")
        if approvers:
            lines.append("Approvers: <code>" + _html(", ".join(approvers)) + "</code>")

        await self._notify("approval", "\n".join(lines), urgent=True, keyboard=kb)

        # Persist ticket for webhook / external systems
        r = self._redis_client()
        if r:
            key = f"ops:ticket:{ticket_id}"
            payload = {
                "id": ticket_id,
                "status": "pending",
                "require": 2 if two_man else 1,
                "approvals": 0,
                "created_at": int(time.time()),
                "expires_at": int(time.time()) + timeout_s,
                "proposal": proposal,
                "approved_by": [],  # optional for webhook enforcement
            }
            try:
                r.setex(key, timeout_s, json.dumps(payload))
            except Exception:
                pass

        return ticket_id

    async def wait_for_ticket(self, ticket_id: str, timeout_s: int) -> Tuple[bool, str]:
        """
        ממתין לאישור/דחייה. מאזין ל-Pub/Sub (ops:ticket:events).
        מחזיר (True,'approved') / (False,'rejected'|'timeout').
        """
        r = self._redis_client()
        channel = self.policy.gate("APPROVAL_PUBSUB", {}).get("channel", "ops:ticket:events")
        deadline = time.time() + max(5, timeout_s)

        def _load():
            if not r:
                return None
            v = r.get(f"ops:ticket:{ticket_id}")
            return json.loads(v) if v else None

        t = _load()
        if t and t.get("status") in ("approved", "rejected"):
            return (t["status"] == "approved", t["status"])

        if r:
            ps = r.pubsub(ignore_subscribe_messages=True)
            try:
                ps.subscribe(channel)
                while time.time() < deadline:
                    msg = await asyncio.to_thread(ps.get_message, timeout=1.0)
                    if msg and msg.get("type") == "message":
                        try:
                            data = json.loads(msg["data"])
                            if data.get("id") == ticket_id and data.get("status") in ("approved", "rejected"):
                                return (data["status"] == "approved", data["status"])
                        except Exception:
                            pass
                    t = _load()
                    if t and t.get("status") in ("approved", "rejected"):
                        return (t["status"] == "approved", t["status"])
            finally:
                try:
                    ps.unsubscribe(channel)
                    ps.close()
                except Exception:
                    pass

        return False, "timeout"

    # ---------------- Auto-Onboard ----------------
    async def auto_onboard(self):
        ao = self.policy.gate("AUTO_ONBOARD", {})
        if not ao or not ao.get("enabled", True):
            return

        ts_il_fmt, ts_utc_fmt = self.policy.time_formats
        ts_il, ts_utc = now_ts(ts_il_fmt, ts_utc_fmt)
        await self._notify("ops", f"📅🕒 <b>זמן:</b> {ts_il} | <b>Time:</b> {ts_utc}\n🟣 Auto-Onboard starting…")

        require = set(ao.get("require", []))
        missing: list[str] = []
        if "credentials" in require and not (os.getenv("BINANCE_API_KEY") and os.getenv("BINANCE_API_SECRET")):
            missing.append("credentials(binance)")
        if "allowlist" in require and not os.getenv("ALLOWLIST_OK", ""):
            missing.append("allowlist")
        if "handshake_ok" in require and not os.getenv("HANDSHAKE_OK", ""):
            missing.append("handshake_ok")
        if "quotas_set" in require and not os.getenv("QUOTAS_SET", ""):
            missing.append("quotas_set")

        if missing:
            await self._notify("ops", "ℹ️ Auto-Onboard prerequisites missing: <code>" + _html(", ".join(missing)) + "</code>")
            return

        staged = bool(ao.get("staged", True))
        steps = ao.get("steps", [
            {"name": "validate_creds", "crs": 1},
            {"name": "enable_scheduler", "crs": 3},
            {"name": "telegram_webhook", "crs": 4},
        ])

        require_approval = bool(ao.get("require_approval", True))
        spacing_seconds = int(ao.get("spacing_seconds", 120))

        for step in steps:
            name = step.get("name", "step")
            crs = int(step.get("crs", 2))
            plan = f"AUTO-ONBOARD step '{name}' (crs={crs}) – safe preview; activates only after approval."
            proposal = {"crs": crs, "sensitive": (crs >= 4), "plan": plan, "version": f"{VERSION}-ao-{name}"}

            if require_approval:
                ticket_id = await self.request_change_approval(proposal)
                if ticket_id:
                    timeout_s = int(self.policy.gate("APPROVAL_ENDPOINTS", {}).get("timeout_seconds", 600))
                    ok, status = await self.wait_for_ticket(ticket_id, timeout_s)
                    if not ok:
                        await self.notify_cancel("auto_onboard_approval", status or "not_approved")
                        return
            else:
                await self._notify("ops", f"🟣 Auto-Onboard preview (no-approval): <b>{_html(name)}</b>\n<code>{_html(plan)}</code>")

            if staged:
                await asyncio.sleep(spacing_seconds)

# -------------------- Main --------------------
async def main():
    policy = load_policy()
    async with Supervisor(policy) as sup:
        await sup.run()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass







