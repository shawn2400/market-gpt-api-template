# tools/generate_stubs.py
from __future__ import annotations
import os
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]

ROUTES = [
"routes.executors","routes.notify_hooks","routes.admin","routes.admin_control","routes.ai_analyze",
"routes.analytics","routes.anchor","routes.auto_trade","routes.binance_status","routes.calibration",
"routes.context","routes.dashboard","routes.dashboard_live","routes.debug","routes.debug_auth",
"routes.debug_binance","routes.debug_env","routes.debug_hmac","routes.decision","routes.executor_control",
"routes.executor_extra","routes.executor_status","routes.executors_grid_export","routes.export","routes.grid",
"routes.guard_smoke","routes.health_compat","routes.indicators","routes.indicators_extra","routes.locked_report",
"routes.manage_state","routes.market","routes.market_extra","routes.multi_scan","routes.news","routes.ops_approval",
"routes.ops_approve","routes.ops_guard","routes.ops_ticket","routes.order_modify","routes.orderbook",
"routes.orderflow","routes.orders","routes.orders_utils","routes.pnl","routes.portfolio","routes.precision",
"routes.provider_cryptopanic","routes.public_feed","routes.reconcile","routes.review_analytics","routes.risk",
"routes.risk_tools","routes.root","routes.root_aliases","routes.rpc","routes.scan_now_alias","routes.scan_public",
"routes.scheduler_ai","routes.snapshot","routes.state","routes.strategy","routes.system_autopilot","routes.telegram",
"routes.telegram_callbacks","routes.telegram_fallback","routes.telegram_ping","routes.telegram_push_status",
"routes.telegram_webhook_secure","routes.trade_approvals","routes.trade_autoscale","routes.trade_sink","routes.ui",
"routes.ui_grid","routes.utils","routes.ws","routes.ws_health","routes.ws_stream","routes.ws_user_status","routes.ws_user_stream"
]

# סטאבים ל-utils שהזכרת
UTILS = {
    # קיימים מהסעיף הראשון – אם כבר כתבת אותם ידנית, הסקריפט ידלג
    "utils/anti_replay.py": """from typing import Optional, Dict, Any, Tuple
def verify_request(x_timestamp: Optional[str], x_nonce: Optional[str], x_signature: Optional[str], path: str, payload: Dict[str, Any], require_signature: bool=True) -> Tuple[bool,str]:
    return True, "ok"
""",
    "utils/telegram_notifier.py": """import asyncio
class TelegramNotifier:
    @staticmethod
    async def send_ops_action_result(symbol: str, action_name: str) -> None:
        await asyncio.sleep(0)
""",
    "utils/guard_stop.py": """def ensure_protective_stop(symbol: str, *, prefer_mode: str = "native") -> None:
    return None
""",
    "utils/order_ids.py": """import time, hashlib
ROLE_MAP={"ENTRY":"ENTRY","BE":"BE","TRAIL":"TRAIL","SL":"SL","TP":"TP","TP1":"TP1","TP2":"TP2","TP3":"TP3","CLOSE":"CLOSE","SL@BE":"SL@BE"}
def _coid_fit(s:str,limit:int=32)->str:
    if len(s)<=limit: return s
    h=hashlib.md5(s.encode()).hexdigest()[:7]
    return s[:limit-(1+len(h))]+"_"+h
def build_client_order_id(symbol:str, side:str, role:str="ENTRY")->str:
    return _coid_fit(f"ALG_{symbol.upper()}_{side.upper()}_{ROLE_MAP.get(role, role)}_{int(time.time())}",32)
""",
    "utils/quantize.py": """import math
def _round_step(v, step): return math.floor(v/step+1e-12)*step if step>0 else v
def quantize_price(px, filters, direction="down"):
    tick=float(filters.get("price_tick") or filters.get("tick") or 0.0)
    if tick<=0: return round(px,8)
    return round((_round_step(px, tick) if direction!="up" else math.ceil(px/tick)*tick),8)
def quantize_qty(qty, filters):
    step=float(filters.get("qty_step") or filters.get("step") or 0.0)
    if step<=0: return round(qty,8)
    return round(_round_step(qty, step),8)
""",
    # ה־utils הנוספים שביקשת כסטאבים ריקים אך עם שמות/חתימות שימושיים
    "utils/idempotency.py": """# idem_for_request: סטאב נו-אופ
from typing import Callable, Any
def idem_for_request(key: str, fn: Callable[[], Any]) -> Any:
    return fn()
""",
    "utils/metrics_tracker.py": """# סטאב למטריקות
_last_entry_score=None
_last_slip_estimate_bps=None
def inc_counter(name:str, value:int=1): pass
def set_last_entry_score(v): global _last_entry_score; _last_entry_score=v
def set_last_slip_estimate_bps(v): global _last_slip_estimate_bps; _last_slip_estimate_bps=v
def observe_time_to_tp1(symbol:str, seconds:float): pass
""",
    "utils/pretrade_checklist.py": """# סטאב – החזרות ברירת מחדל
def compute_pretrade_score(*args, **kwargs) -> float: return 0.0
def estimate_impact_slip_bps(*args, **kwargs) -> float: return 0.0
""",
    "utils/exec_decider.py": """def decide_execution_mode(*args, **kwargs): return "market"
""",
    "utils/tp_helper.py": """def maybe_merge_close_tps(*args, **kwargs): return None
def maybe_rearm_on_bounce(*args, **kwargs): return None
def anti_stale_nudge(*args, **kwargs): return None
""",
    "utils/time_stop.py": """def should_time_stop(*args, **kwargs) -> bool: return False
def time_stop_decision(*args, **kwargs): return {"action":"hold"}
""",
    "utils/trade_executor.py": """# סטאב – מבצע נו-אופ
def place_futures_market(*args, **kwargs): return {"ok": True, "orderId": 0}
def execute_trade_live(*args, **kwargs): return {"ok": True, "details": {}}
""",
    "utils/position_sizing.py": """def ensure_final_qty(symbol:str, raw_qty:float) -> float: return float(raw_qty or 0.0)
""",
}

ROUTE_TEMPLATE = """# {mod}.py
from fastapi import APIRouter
router = APIRouter(prefix="/{prefix}", tags=["{tag}"])
@router.get("/ping")
def ping():
    return {{"ok": True, "route": "{mod}", "ping": "pong"}}
"""

def ensure_pkg(path: Path):
    if not path.exists():
        path.mkdir(parents=True, exist_ok=True)
    init = path / "__init__.py"
    if not init.exists():
        init.write_text("")

def main():
    # חבילות
    ensure_pkg(BASE / "routes")
    ensure_pkg(BASE / "utils")
    # routes
    for dotted in ROUTES:
        mod = dotted.split(".", 1)[1]
        fpath = BASE / "routes" / f"{mod}.py"
        if not fpath.exists():
            fpath.write_text(ROUTE_TEMPLATE.format(mod=f"routes.{mod}", prefix=mod.replace("_","-"), tag=mod))
    # utils
    for rel, content in UTILS.items():
        fpath = BASE / rel
        if not fpath.parent.exists():
            ensure_pkg(fpath.parent)
        if not fpath.exists():
            fpath.write_text(content)

if __name__ == "__main__":
    main()
