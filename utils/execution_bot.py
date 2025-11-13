"""
ExecutionBot - Unified Trade Execution Controller
==================================================
Central wrapper for opening, managing, and closing positions.

Routes, Telegram, and Auto Executor communicate only with this class.
Actual logic remains in:
- trade_executor.py
- trade_manager.py
- binance_client.py

Author: AlgoGPT Team - MetaBrain v9.1
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional, Literal

FlowType = Literal["MARKET", "HYBRID"]


class ExecutionBot:
    """
    Execution & Management Bot
    ---------------------------
    Central wrapper for opening positions, managing, and closing.

    Purpose:
    - Single entry point: open_position / close_position / manage_once
    - routes/telegram/auto-executor communicate only with this class
    - Actual logic remains in:
        - trade_executor.py
        - trade_manager.py
        - binance_client.py
    """

    def __init__(self, logger: Optional[logging.Logger] = None) -> None:
        self.log = logger or logging.getLogger("algogpt.execution_bot")

    async def open_position(
        self,
        ticket_exec: Dict[str, Any],
        *,
        source: str = "api",
    ) -> Dict[str, Any]:
        """
        Open a single trade based on ticket_exec.

        Args:
            ticket_exec: dict with everything needed to execute a trade
                        (symbol, side, position_type, leverage, budget/qty, sl/tp etc).
            source: where the trade came from ("api", "approval", "telegram", "auto" etc).

        Returns:
            dict with status, flow, symbol, side, position_id, orders, reason etc.
        """
        symbol = ticket_exec.get("symbol")
        side = ticket_exec.get("side")
        self.log.info(f"ExecutionBot.open_position called: symbol={symbol} side={side} source={source}")

        # 1) Basic validation (lean - not repeating what's already in Pydantic in route)
        try:
            self._validate_ticket_basic(ticket_exec)
        except Exception as e:
            raise

        # 2) Flow selection (MARKET / HYBRID) - instead of logic that was in /execute and /approve
        flow = self._select_flow(ticket_exec, source=source)

        # 3) Approval gate - if approval needed, return pending_approval
        if self._needs_approval(ticket_exec, source=source):
            self.log.info(
                f"ExecutionBot: trade requires approval. Marking as pending_approval (symbol={symbol} side={side} source={source})"
            )
            return {
                "status": "pending_approval",
                "flow": flow,
                "symbol": symbol,
                "side": side,
                "reason": "Awaiting approval",
            }

        # 4) Execute in production - wrapper over trade_executor / binance_client
        try:
            exec_result = await self._execute_flow(flow, ticket_exec, source=source)
            return {
                "status": exec_result.get("status", "opened"),
                "flow": flow,
                "symbol": symbol,
                "side": side,
                "position_id": exec_result.get("position_id"),
                "entry_orders": exec_result.get("entry_orders"),
                "sl_order": exec_result.get("sl_order"),
                "tp_orders": exec_result.get("tp_orders"),
                "raw": exec_result,
            }

        except Exception as exc:
            self.log.exception(
                f"ExecutionBot.open_position failed: symbol={symbol} side={side} source={source}"
            )
            return {
                "status": "error",
                "flow": flow,
                "symbol": symbol,
                "side": side,
                "reason": str(exc),
            }

    async def close_position(
        self,
        *,
        position_id: Optional[str] = None,
        symbol: Optional[str] = None,
        reason: str = "",
    ) -> Dict[str, Any]:
        """
        Close a position (by position_id or symbol - depending on what exists in the system).

        Args:
            position_id: internal position identifier (if exists in system).
            symbol: symbol (BTCUSDT etc) if no position_id.
            reason: logical reason for closing (logs, PnL etc).

        Returns:
            dict with status, symbol, position_id, raw result
        """
        self.log.info(
            f"ExecutionBot.close_position called: position_id={position_id} symbol={symbol} reason={reason}"
        )

        try:
            if position_id:
                raise NotImplementedError("Implement close by position_id")
            elif symbol:
                raise NotImplementedError("Implement close by symbol")
            else:
                raise ValueError("Either position_id or symbol must be provided")

        except Exception as exc:
            self.log.exception(
                f"ExecutionBot.close_position failed: position_id={position_id} symbol={symbol}"
            )
            return {
                "status": "error",
                "symbol": symbol,
                "position_id": position_id,
                "reason": str(exc),
            }

    async def manage_once(self) -> Dict[str, Any]:
        """
        Single management cycle (one tick) - move SL/TP, BE, Trailing etc.

        Intended for scheduler/auto-executor execution,
        not to open infinite loop here.

        Returns:
            dict with status and actions
        """
        self.log.info("ExecutionBot.manage_once called")

        try:
            raise NotImplementedError("Connect to trade_manager.manage_open_trades()")

        except Exception as exc:
            self.log.exception("ExecutionBot.manage_once failed")
            return {
                "status": "error",
                "reason": str(exc),
            }

    def _validate_ticket_basic(self, ticket_exec: Dict[str, Any]) -> None:
        """
        Basic validation only - to catch gross errors before execution.
        (Other validation already done in Pydantic + in executor itself).
        """
        symbol = ticket_exec.get("symbol")
        side = ticket_exec.get("side")
        budget = ticket_exec.get("budget") or ticket_exec.get("quantity")

        if not symbol:
            raise ValueError("Missing symbol in ticket_exec")
        if side not in ("LONG", "SHORT", "BUY", "SELL"):
            raise ValueError(f"Invalid side: {side!r}")
        if budget is not None and float(budget) <= 0:
            raise ValueError("Budget/quantity must be > 0")

    def _select_flow(
        self,
        ticket_exec: Dict[str, Any],
        *,
        source: str,
    ) -> FlowType:
        """
        Flow selection (MARKET / HYBRID) based on logic that was in /execute and /approve.

        TODO: Copy the logic that was in routes/trade.py:
        - If needs approval → HYBRID
        - If coming from approval/telegram → MARKET
        - If flags in ENV → consider them
        """
        if any(ticket_exec.get(k) is not None for k in ("tp1", "tp2", "tp3", "sl")):
            return "HYBRID"
        if (ticket_exec.get("quantity") is None) and (ticket_exec.get("budget_usd") is not None or ticket_exec.get("budget") is not None):
            return "HYBRID"
        return "MARKET"

    def _needs_approval(self, ticket_exec: Dict[str, Any], *, source: str) -> bool:
        """
        Does this trade need to go through approval route (telegram / webhook) before actual execution.

        Sources that already passed approval or execute immediately:
        - "approval", "ops_approval", "ops_approval_get", "ops_approval_fallback" - already approved
        - "telegram", "telegram_callback" - user-initiated, execute immediately
        - "auto_trade", "autopilot" - internal automation, execute immediately (confirm_first handled internally)
        """
        if source in (
            "approval",
            "ops_approval",
            "ops_approval_get",
            "ops_approval_fallback",
            "ops_approval_get_fallback",
            "telegram",
            "telegram_callback",
            "auto_trade",
            "autopilot",
        ):
            return False

        force_approve_env = os.getenv("REQUIRE_TELEGRAM_APPROVAL", "0").lower() in ("1", "true", "yes", "on")
        need_approval = bool(ticket_exec.get("require_approval") or ticket_exec.get("confirm_first") or force_approve_env)
        return need_approval

    async def _execute_flow(
        self,
        flow: FlowType,
        ticket_exec: Dict[str, Any],
        *,
        source: str,
    ) -> Dict[str, Any]:
        """
        Actual trade execution based on flow.

        Here we connect to actual functions from trade_executor.py
        (e.g. execute_trade_live / execute_trade_hybrid etc).
        """
        if flow == "MARKET":
            return await self._execute_trade_direct(ticket_exec)
        elif flow == "HYBRID":
            return await self._execute_trade_hybrid(ticket_exec)
        else:
            raise ValueError(f"Unknown flow: {flow}")

    async def _execute_trade_direct(self, ticket: Dict[str, Any]) -> Dict[str, Any]:
        """
        Direct MARKET execution (moved from routes/trade.py).
        Fast-path through internal adapter if available.
        """
        try:
            from utils.trade_executor import place_futures_market
            return await place_futures_market(ticket)
        except Exception:
            pass

        try:
            from binance.client import Client
        except Exception:
            return {"ok": False, "error": "binance_client_unavailable"}

        try:
            api_key = os.getenv("BINANCE_API_KEY", "").strip()
            api_sec = os.getenv("BINANCE_API_SECRET", "").strip()
            if not (api_key and api_sec):
                return {"ok": False, "error": "binance_keys_missing"}
            client = Client(api_key, api_sec)

            symbol = str(ticket.get("symbol", "")).upper()
            side = str(ticket.get("side", "")).upper()
            qty = float(ticket.get("qty") or ticket.get("quantity") or 0)
            leverage = int(ticket.get("leverage") or 0)
            if not (symbol and side in ("BUY", "SELL") and qty > 0 and leverage > 0):
                return {"ok": False, "error": "bad_ticket_params"}

            try:
                client.futures_change_leverage(symbol=symbol, leverage=leverage)
            except Exception as e:
                self.log.warning(f"futures_change_leverage failed: {e}")

            from utils.order_ids import build_client_order_id
            
            base_kwargs: Dict[str, Any] = {
                "symbol": symbol,
                "side": side,
                "type": "MARKET",
                "quantity": qty,
                "newClientOrderId": build_client_order_id(symbol, side, role="ENTRY"),
            }

            pos_side_supplied = str(ticket.get("position_side") or ticket.get("positionSide") or "").upper()
            attempt_order = dict(base_kwargs)
            if pos_side_supplied:
                attempt_order["positionSide"] = pos_side_supplied
            elif os.getenv("POSITION_MODE_OVERRIDE", "").strip().lower() in ("hedge", "hedged") or \
                 os.getenv("BINANCE_FORCE_HEDGE_MODE", "").strip().lower() in ("1", "true", "yes", "on"):
                attempt_order["positionSide"] = "LONG" if side == "BUY" else "SHORT"

            try:
                order = client.futures_create_order(**attempt_order)
                return {"ok": True, "exchange": "binance_futures", "order": order}
            except Exception as e1:
                if "code=-4061" not in str(e1) and "position side does not match" not in str(e1).lower():
                    self.log.error(f"futures_create_order failed: {e1}")
                    return {"ok": False, "error": "order_failed", "detail": str(e1)}
                try:
                    if "positionSide" in attempt_order:
                        retry_kwargs = dict(base_kwargs)
                    else:
                        retry_kwargs = dict(base_kwargs)
                        retry_kwargs["positionSide"] = "LONG" if side == "BUY" else "SHORT"
                    order = client.futures_create_order(**retry_kwargs)
                    return {"ok": True, "exchange": "binance_futures", "order": order, "retry": True}
                except Exception as e2:
                    self.log.error(f"futures_create_order after 4061 retry failed: {e2}")
                    return {
                        "ok": False,
                        "error": "order_failed",
                        "detail": str(e2),
                        "first_error": str(e1),
                    }
        except Exception as e:
            self.log.error(f"order_execute_direct_failed: {e}")
            return {"ok": False, "error": "order_failed", "detail": str(e)}

    async def _execute_trade_hybrid(self, ticket: Dict[str, Any]) -> Dict[str, Any]:
        """
        HYBRID execution with TP/SL management (moved from routes/trade.py).
        Prefers live adapter (with TP/SL etc handling).
        """
        import asyncio
        import inspect
        
        exec_live = None
        exec_live_async = None
        try:
            from utils.trade_executor import execute_trade_live as _live
            exec_live = _live
        except Exception:
            pass
        try:
            from utils.trade_executor import execute_trade_live_async as _live_async
            exec_live_async = _live_async
        except Exception:
            pass

        if exec_live_async is None and exec_live is None:
            return {"ok": False, "error": "execute_trade_live_missing"}

        symbol = str(ticket.get("symbol", "")).upper()
        side = str(ticket.get("side", "")).upper()
        qty = ticket.get("qty") or ticket.get("quantity")
        leverage = int(ticket.get("leverage") or ticket.get("lev") or 0)
        pos_side = str(
            ticket.get("position_side") or ticket.get("positionSide") or ("LONG" if side == "BUY" else "SHORT")
        ).upper()

        tps_raw = [ticket.get("tp1"), ticket.get("tp2"), ticket.get("tp3")]
        tp_targets = [float(x) for x in tps_raw if x is not None and str(x) not in ("0", "0.0") and float(x) > 0]
        sl_targets = [float(ticket.get("sl"))] if (ticket.get("sl") not in (None, 0, "0", "0.0")) else None

        if not (symbol and side in ("BUY", "SELL") and leverage > 0):
            return {"ok": False, "error": "bad_ticket_params"}

        base_kwargs: Dict[str, Any] = dict(
            symbol=symbol,
            side=side,
            budget=ticket.get("budget") or ticket.get("budget_usd"),
            leverage=leverage,
            dry_run=bool(ticket.get("dry_run", False)),
            quantity=(float(qty) if qty is not None else None),
            entry=None,
            tp_targets=tp_targets or None,
            sl_targets=sl_targets or None,
            tp_splits=ticket.get("tp_splits"),
            sl_splits=None,
            confirm_first=False,
            telegram_chat_id=int(os.getenv("TELEGRAM_CHAT_ID") or 0),
            position_side=pos_side,
            reduce_only=bool(ticket.get("reduce_only", False)),
            quality=ticket.get("quality") or ticket.get("score"),
            score=ticket.get("score") or ticket.get("quality"),
        )

        def _filter_kwargs_for_callable(fn, kwargs):
            try:
                sig = inspect.signature(fn)
                allowed = set(sig.parameters.keys())
                return {k: v for k, v in kwargs.items() if k in allowed and v is not None}
            except Exception:
                bad = {"tp_kind", "sl_kind", "entry_kind", "entry_offset", "tp_offset", "sl_offset"}
                return {k: v for k, v in kwargs.items() if k not in bad and v is not None}

        if exec_live_async is not None:
            try:
                return await exec_live_async(base_kwargs)
            except TypeError:
                clean = _filter_kwargs_for_callable(exec_live_async, base_kwargs)
                return await exec_live_async(clean)

        try:
            if inspect.iscoroutinefunction(exec_live):
                return await exec_live(base_kwargs)
            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(None, lambda: exec_live(base_kwargs))
        except TypeError:
            clean = _filter_kwargs_for_callable(exec_live, base_kwargs)
            if inspect.iscoroutinefunction(exec_live):
                return await exec_live(**clean)
            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(None, lambda: exec_live(**clean))
