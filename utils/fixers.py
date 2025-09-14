# FILE: utils/fixers.py
from __future__ import annotations
import asyncio
import json
import os
from typing import Any, Dict, Optional, Tuple, Callable, List

import aiohttp

NotifyFn = Callable[[str], Any]

class BuildCtx:
    def __init__(
        self,
        session: aiohttp.ClientSession,
        notify: NotifyFn,
        policy: Dict[str, Any],
        sanitize_redis_fn,
        redis_self_test_fn,
        persist_redis_fix_fn,     # async (new_url)->bool
        redeploy_primary_fn,      # async (reason)->None
    ):
        self.session = session
        self.notify = notify
        self.policy = policy
        self.sanitize_redis_fn = sanitize_redis_fn
        self.redis_self_test_fn = redis_self_test_fn
        self.persist_redis_fix_fn = persist_redis_fix_fn
        self.redeploy_primary_fn = redeploy_primary_fn

        # ENV that fixers may need:
        self.REDIS_URL = os.getenv("REDIS_URL", "")
        self.PRIMARY_PUBLIC_HOST = os.getenv("PRIMARY_PUBLIC_HOST", "").rstrip("/")
        self.PRIMARY_API_TOKEN = os.getenv("PRIMARY_API_TOKEN", "")
        self.PUBLIC_HOST = os.getenv("PUBLIC_HOST", "").rstrip("/")
        self.TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
        self.TELEGRAM_WEBHOOK_SECRET = os.getenv("TELEGRAM_WEBHOOK_SECRET", "")

# ---------- Base ----------
class Fixer:
    name = "base"
    def __init__(self, ctx: BuildCtx, cfg: Dict[str, Any]):
        self.ctx = ctx
        self.cfg = cfg
    async def run(self) -> None:
        raise NotImplementedError

# ---------- Redis Fixer ----------
class RedisFixer(Fixer):
    name = "redis"
    async def run(self) -> None:
        if not self.cfg.get("enabled", True):
            return
        url = self.ctx.REDIS_URL
        if not url:
            return
        new_url = self.ctx.sanitize_redis_fn(url)
        if new_url != url:
            os.environ["REDIS_URL"] = new_url
            ok, reason = await self.ctx.redis_self_test_fn(self.ctx.session, new_url)
            if ok:
                await self.ctx.notify(f"✅ Redis fixed by sanitizer.\n<code>{repr(new_url)}</code>")
                if self.cfg.get("persist_to_render", False):
                    persisted = await self.ctx.persist_redis_fix_fn(new_url)
                    if persisted:
                        await self.ctx.notify("📌 Persisted REDIS_URL to Render and triggered redeploy.")
                    else:
                        await self.ctx.notify("ℹ️ Could not persist REDIS_URL via Render API (missing perms or API mismatch).")
            else:
                await self.ctx.notify(f"⚠️ Redis still failing after sanitize: <code>{reason}</code>")

# ---------- Primary Health Fixer ----------
class PrimaryFixer(Fixer):
    name = "primary"
    async def run(self) -> None:
        if not self.cfg.get("enabled", True):
            return
        host = self.ctx.PRIMARY_PUBLIC_HOST
        if not host:
            return
        url = host + "/health"
        try:
            async with self.ctx.session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as r:
                if r.status != 200:
                    await self.ctx.notify(f"⚠️ Primary /health HTTP {r.status}, attempting redeploy…")
                    await self.ctx.redeploy_primary_fn("fixer:primary_http")
                    return
                data = await r.json()
                if not bool(data.get("ok", False)):
                    await self.ctx.notify("⚠️ Primary health not OK, attempting redeploy…")
                    await self.ctx.redeploy_primary_fn("fixer:primary_not_ok")
        except Exception as e:
            await self.ctx.notify(f"⚠️ Primary down ({e}), attempting redeploy…")
            await self.ctx.redeploy_primary_fn("fixer:primary_down")

# ---------- Telegram Webhook Fixer ----------
class TelegramWebhookFixer(Fixer):
    name = "telegram_webhook"
    async def run(self) -> None:
        if not self.cfg.get("enabled", True):
            return
        token = self.ctx.TELEGRAM_TOKEN
        public_host = self.ctx.PUBLIC_HOST
        secret = self.ctx.TELEGRAM_WEBHOOK_SECRET
        route = self.cfg.get("route", "/telegram/webhook")
        qkey  = self.cfg.get("query_secret_key", "secret")
        if not (token and public_host and secret):
            return
        set_url = f"https://api.telegram.org/bot{token}/setWebhook"
        webhook = f"{public_host.rstrip('/')}{route}?{qkey}={secret}"
        payload = {"url": webhook, "allowed_updates": ["message", "callback_query"]}
        try:
            async with self.ctx.session.post(set_url, json=payload, timeout=aiohttp.ClientTimeout(total=10)) as r:
                _ = await r.json()
            # verify
            info_url = f"https://api.telegram.org/bot{token}/getWebhookInfo"
            async with self.ctx.session.get(info_url, timeout=aiohttp.ClientTimeout(total=10)) as r:
                data = await r.json()
            if data.get("ok") and data.get("result", {}).get("url") == webhook:
                await self.ctx.notify("✅ Telegram webhook set & verified.")
            else:
                await self.ctx.notify("⚠️ Telegram webhook not verified; check PUBLIC_HOST/secret/route.")
        except Exception as e:
            await self.ctx.notify(f"⚠️ Telegram webhook error: {e}")

# ---------- Executor Ping Fixer ----------
class ExecutorPingFixer(Fixer):
    name = "executor_ping"
    async def run(self) -> None:
        if not self.cfg.get("enabled", True):
            return
        host = self.ctx.PRIMARY_PUBLIC_HOST
        if not host:
            return
        headers = {}
        if self.cfg.get("require_token", True) and self.ctx.PRIMARY_API_TOKEN:
            headers["Authorization"] = f"Bearer {self.ctx.PRIMARY_API_TOKEN}"
        url = host + "/executor/ping"
        try:
            async with self.ctx.session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as r:
                txt = await r.text()
                # לא נכשלים אם {"ok":false}; רק מודיעים
                if r.status != 200:
                    await self.ctx.notify(f"⚠️ /executor/ping HTTP {r.status}: {txt[:180]}")
                elif '"ok":false' in txt.replace(" ", ""):
                    await self.ctx.notify("ℹ️ /executor/ping responded ok:false (בדוק הרשאות/טוקן).")
        except Exception as e:
            await self.ctx.notify(f"⚠️ /executor/ping error: {e}")

# ---------- Render Env Sync Fixer ----------
class RenderEnvSyncFixer(Fixer):
    name = "render_env_sync"
    async def run(self) -> None:
        # בפועל ה-Redis לשימור מתבצע ע"י RedisFixer → persist_redis_fix_fn
        # כאן נשאיר קריאת מקום לפיקסרים עתידיים/ENV נוספים.
        return

# ---------- Factory / Manager ----------
def build_fixers(ctx: BuildCtx, config: Dict[str, Any]) -> List[Fixer]:
    fixers: List[Fixer] = []
    if not config.get("enabled", True):
        return fixers
    if "redis" in config:            fixers.append(RedisFixer(ctx, config["redis"]))
    if "primary" in config:          fixers.append(PrimaryFixer(ctx, config["primary"]))
    if "telegram_webhook" in config: fixers.append(TelegramWebhookFixer(ctx, config["telegram_webhook"]))
    if "executor_ping" in config:    fixers.append(ExecutorPingFixer(ctx, config["executor_ping"]))
    if "render_env_sync" in config:  fixers.append(RenderEnvSyncFixer(ctx, config["render_env_sync"]))
    return fixers

class FixerManager:
    def __init__(self, ctx: BuildCtx, config: Dict[str, Any]):
        self.ctx = ctx
        self.config = config
        self.fixers = build_fixers(ctx, config)

    async def run_all(self):
        for fx in self.fixers:
            try:
                await fx.run()
            except Exception as e:
                await self.ctx.notify(f"🟡 Fixer '{fx.name}' error: {e}")
