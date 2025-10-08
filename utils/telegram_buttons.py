# utils/telegram_buttons.py
from __future__ import annotations
from typing import Dict, Any, List, Optional

from .telegram_notifier import make_callback

def approval_kb_for_trade(idem: str, ticket_url: Optional[str] = None) -> Dict[str, Any]:
    rows: List[List[Dict[str,Any]]] = [
        [
            {"text": "✅ אישור / Approve", "callback_data": make_callback("APPROVE", trade_id=idem)},
            {"text": "❌ דחייה / Reject",  "callback_data": make_callback("REJECT",  trade_id=idem)},
        ]
    ]
    if ticket_url:
        rows.append([{"text": "🧾 Ticket", "url": ticket_url}])
    return {"inline_keyboard": rows}

def ops_action_kb(symbol: str) -> Dict[str,Any]:
    return {"inline_keyboard":[
        [{"text":"⚙️ Manage Again","callback_data": make_callback("MANAGE_AGAIN", symbol=symbol)}],
        [{"text":"🧹 Cancel TPs","callback_data": make_callback("CANCEL_TPS", symbol=symbol)},
         {"text":"➗ Close 50%","callback_data": make_callback("CLOSE_50", symbol=symbol, pct=50.0)}],
    ]}
