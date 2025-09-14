# utils/telegram_callbacks.py
from __future__ import annotations
import logging
from typing import Dict, Any

from utils.trade_executor import ConfirmStore
from utils.telegram_notifier import notify_info, notify_error

log = logging.getLogger("algogpt.telegram_callbacks")

async def handle_callback_action(callback_data: str, chat_id: int, username: str | None = None) -> Dict[str, Any]:
    """
    פורמט callback_data: CONFIRM:APPROVE:cid12345
    """
    try:
        parts = callback_data.strip().split(":")
        if len(parts) != 3 or parts[0] != "CONFIRM":
            return {"ok": False, "reason": "invalid_format"}

        action = parts[1].upper()
        confirm_id = parts[2]
        approver = username or str(chat_id)

        if action == "APPROVE":
            ConfirmStore.approve(confirm_id, approver=approver)
            await notify_info(f"אושר ✅ ע״י {approver}")
            return {"ok": True, "action": "approved"}

        elif action == "REJECT":
            ConfirmStore.reject(confirm_id, approver=approver)
            await notify_info(f"נדחה ❌ ע״י {approver}")
            return {"ok": True, "action": "rejected"}

        else:
            return {"ok": False, "reason": "unknown_action"}

    except Exception as e:
        log.warning({"event": "callback_handler_error", "error": str(e)})
        await notify_error(f"שגיאה בטיפול בכפתור: {str(e)}")
        return {"ok": False, "reason": str(e)}
