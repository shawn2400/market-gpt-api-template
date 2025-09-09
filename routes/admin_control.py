# routes/admin_control.py
from __future__ import annotations
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import os, asyncio

router = APIRouter(prefix="/admin", tags=["Admin"], include_in_schema=False)

class ControlIn(BaseModel):
    action: str  # start|stop|status|manage_once|mute|set_webhook
    target: str  # executor|ws-user|manager|telegram
    args: dict | None = None

def _bool_env(name: str, default: str = "0") -> bool:
    return os.getenv(name, default).strip().lower() in ("1","true","yes","on")

@router.post("/control")
async def admin_control(body: ControlIn):
    action = body.action.strip().lower()
    target = body.target.strip().lower()
    args = body.args or {}

    if target == "executor":
        from utils.auto_executor import start_executor, stop_executor, is_executor_running
        if action == "start":
            start_executor()
        elif action == "stop":
            stop_executor()
        elif action == "status":
            return {"ok": True, "running": bool(is_executor_running())}
        else:
            raise HTTPException(400, "unknown action for executor")

        return {"ok": True}

    elif target == "ws-user":
        try:
            from utils import ws_user_stream as wsus
        except Exception:
            wsus = None

        if action == "start":
            if not wsus:
                raise HTTPException(500, "ws module not available")
            await wsus.start()
            return {"ok": True, "started": True}
        elif action == "stop":
            if wsus:
                await wsus.stop()
            return {"ok": True, "stopped": True}
        elif action == "status":
            if not wsus:
                return {"ok": True, "running": False, "error": "module_not_loaded"}
            return {"ok": True, **wsus.status()}
        else:
            raise HTTPException(400, "unknown action for ws-user")

    elif target == "manager":
        if action == "manage_once":
            try:
                from utils.trade_manager import manage_open_trades
                await manage_open_trades()
                return {"ok": True, "managed": True}
            except Exception as e:
                raise HTTPException(500, f"manage failed: {e}")
        elif action == "status":
            return {"ok": True, "allow_manage": _bool_env("ALLOW_MANAGE_OPEN_TRADES","1")}
        else:
            raise HTTPException(400, "unknown action for manager")

    elif target == "telegram":
        if action == "mute":
            st = bool(args.get("state", True))
            os.environ["TELEGRAM_ADMIN_ONLY"] = "1" if st else "0"
            return {"ok": True, "mute": st}
        elif action == "set_webhook":
            # נוח להשתמש ברואטר הקיים שלך; כאן רק דוגמה בסיסית
            import httpx
            token = os.getenv("TELEGRAM_BOT_TOKEN","").strip()
            secret = os.getenv("TELEGRAM_WEBHOOK_SECRET","").strip()
            host = os.getenv("PUBLIC_HOST","").strip()
            if not (token and secret and host):
                raise HTTPException(400, "missing bot token/secret/public host")
            url = f"https://api.telegram.org/bot{token}/setWebhook"
            async with httpx.AsyncClient(timeout=10.0) as cli:
                r = await cli.post(url, data={"url": f"{host}/telegram/webhook", "secret_token": secret, "drop_pending_updates": "true"})
                r.raise_for_status()
                return {"ok": True, "telegram_response": r.json()}
        else:
            raise HTTPException(400, "unknown action for telegram")

    else:
        raise HTTPException(400, "unknown target")
