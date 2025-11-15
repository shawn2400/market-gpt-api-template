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

FlowType = Literal["MARKET", "HYBRID", "LIMIT"]


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
        
        # 🛡️ Initialize protection systems (TradingGatekeeper + SmartRouter)
        try:
            from utils.trading_gatekeeper import TradingGatekeeper
            self._gatekeeper = TradingGatekeeper()
            self.log.info("✅ TradingGatekeeper loaded")
        except Exception as e:
            self.log.warning(f"⚠️ TradingGatekeeper unavailable: {e}")
            self._gatekeeper = None
        
        try:
            from utils.order_router import SmartOrderRouter
            self._order_router = SmartOrderRouter()
            self.log.info("✅ SmartOrderRouter loaded")
        except Exception as e:
            self.log.warning(f"⚠️ SmartOrderRouter unavailable: {e}")
            self._order_router = None
        
        # ⏱️ Initialize Order Timeout Monitor
        try:
            from utils.order_timeout_monitor import get_timeout_monitor
            from utils.binance_client import get_futures_client
            client = get_futures_client()
            self._timeout_monitor = get_timeout_monitor(client)
            self.log.info("✅ OrderTimeoutMonitor loaded and started")
        except Exception as e:
            self.log.warning(f"⚠️ OrderTimeoutMonitor unavailable: {e}")
            self._timeout_monitor = None

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

        # 🛡️ 1.5) TradingGatekeeper validation - CRITICAL PROTECTION LAYER
        if self._gatekeeper:
            try:
                gatekeeper_result = self._gatekeeper.validate_trade(
                    symbol=symbol,
                    order_type="NEW",
                    trade_quality=ticket_exec.get("quality_score"),
                    atr_pct=ticket_exec.get("atr_pct"),
                    current_price=ticket_exec.get("price") or ticket_exec.get("current_price"),
                    position_side=side,
                    leverage=ticket_exec.get("leverage"),
                    metadata=ticket_exec,
                )
                
                if not gatekeeper_result.approved:
                    self.log.warning(
                        f"🚫 Gatekeeper BLOCKED {symbol}: {gatekeeper_result.reason}"
                    )
                    return {
                        "status": "blocked",
                        "flow": None,
                        "symbol": symbol,
                        "side": side,
                        "reason": gatekeeper_result.reason,
                        "details": gatekeeper_result.details,
                    }
                
                # Apply gatekeeper enforced limits
                if gatekeeper_result.leverage:
                    original_lev = ticket_exec.get("leverage")
                    ticket_exec["leverage"] = min(
                        ticket_exec.get("leverage", 20),
                        gatekeeper_result.leverage
                    )
                    if original_lev != ticket_exec["leverage"]:
                        self.log.info(
                            f"🛡️ Gatekeeper capped leverage: {original_lev}x → {ticket_exec['leverage']}x"
                        )
                
                if gatekeeper_result.max_position_size:
                    ticket_exec["gatekeeper_max_size"] = gatekeeper_result.max_position_size
                
                self.log.info(
                    f"✅ Gatekeeper APPROVED {symbol} | "
                    f"Leverage: {ticket_exec.get('leverage')}x | "
                    f"Filters: {', '.join(gatekeeper_result.filters_passed)}"
                )
                
            except Exception as gate_err:
                self.log.error(f"⚠️ Gatekeeper check failed: {gate_err}", exc_info=True)
                # Fail-open mode: allow trade but log error
                self.log.warning(f"⚠️ Proceeding with trade (gatekeeper failed)")

        # 2) Flow selection (MARKET / HYBRID / LIMIT) - with SmartRouter
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

        # 🛡️ 3.5) Binance ISOLATED positions limit (max 4) - enforce before execution
        try:
            await self._enforce_isolated_limit(symbol, ticket_exec)
        except RuntimeError as iso_err:
            self.log.warning(f"⚠️ ISOLATED limit reached for {symbol}: {iso_err}")
            return {
                "status": "blocked",
                "flow": flow,
                "symbol": symbol,
                "side": side,
                "reason": str(iso_err),
            }

        # 4) Execute in production - wrapper over trade_executor / binance_client
        try:
            exec_result = await self._execute_flow(flow, ticket_exec, source=source)
            
            # 🛡️ REGISTER POSITION ENTRY TIME for 60-second hold protection
            if exec_result.get("status") == "opened":
                try:
                    from utils.advanced_risk_manager import get_risk_manager
                    risk_manager = get_risk_manager()
                    risk_manager.register_position_entry(symbol)
                    self.log.info(f"🛡️ Registered entry time for {symbol} (60-second hold protection)")
                except Exception as reg_err:
                    self.log.warning(f"⚠️ Failed to register entry time for {symbol}: {reg_err}")
            
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
        Flow selection using SmartOrderRouter for intelligent LIMIT/MARKET/HYBRID decisions.
        
        Falls back to legacy logic if router unavailable.
        """
        # 🚀 Try SmartOrderRouter first
        if self._order_router:
            try:
                # 🛡️ CRITICAL: Normalize atr_pct - .get() returns None if key exists but value is None!
                atr_pct = ticket_exec.get("atr_pct")
                if atr_pct is None:
                    atr_pct = 0.02  # Default 2% volatility
                
                decision = self._order_router.route_order(
                    atr_pct=atr_pct,
                    spread_pct=ticket_exec.get("spread_pct"),
                    signal_age_sec=ticket_exec.get("signal_age"),
                    urgency=ticket_exec.get("urgency", "normal"),
                    purpose="ENTRY",
                    book_depth_ok=ticket_exec.get("book_depth_ok", True),
                    position_size_large=(ticket_exec.get("notional") or 0) > 2000,
                )
                ticket_exec["router_meta"] = decision  # Store decision metadata
                order_type = decision.get("order_type", "MARKET")
                
                self.log.info(
                    f"📍 SmartRouter decision: {order_type} | "
                    f"ATR: {ticket_exec.get('atr_pct', 'N/A')}% | "
                    f"Reason: {decision.get('reason', 'N/A')}"
                )
                
                # Map router output to FlowType
                if order_type == "LIMIT":
                    return "LIMIT"
                elif order_type in ("HYBRID", "LIMIT_ESCALATE"):
                    return "HYBRID"
                else:
                    return "MARKET"
                    
            except Exception as router_err:
                self.log.warning(f"⚠️ SmartRouter failed, using legacy flow: {router_err}")
        
        # 📜 Legacy flow selection (backward compatibility)
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

    async def _enforce_isolated_limit(self, symbol: str, ticket_exec: Dict[str, Any]) -> None:
        """
        Enforce Binance's ISOLATED margin limit (max 4 concurrent positions).
        
        If 4 ISOLATED positions already exist and this is a new symbol,
        either downgrade to CROSS margin or raise an error.
        
        Raises:
            RuntimeError: If ISOLATED limit reached and cannot proceed
        """
        try:
            from utils.binance_client import get_client
            
            # Get current positions
            client = get_client()
            positions = client.futures_position_information()
            
            # Count open ISOLATED positions
            isolated_open = [
                p for p in positions
                if float(p.get("positionAmt", 0)) != 0 and p.get("marginType") == "isolated"
            ]
            
            # If we already have a position for this symbol in ISOLATED, allow it
            if symbol in {p["symbol"] for p in isolated_open}:
                self.log.info(f"✅ ISOLATED OK: {symbol} already has ISOLATED position")
                return
            
            # If we have 4 ISOLATED positions and this is a NEW symbol
            if len(isolated_open) >= 4:
                isolated_symbols = [p["symbol"] for p in isolated_open]
                self.log.warning(
                    f"⚠️ ISOLATED LIMIT: 4/4 positions full ({', '.join(isolated_symbols)})"
                )
                
                # Option 1: Auto-downgrade to CROSS margin (safest)
                ticket_exec["margin_type"] = "CROSS"
                ticket_exec["isolated_limit_downgrade"] = True
                self.log.info(f"🔄 Auto-downgraded {symbol} to CROSS margin (ISOLATED limit reached)")
                return
                
                # Option 2: Reject trade (strict mode)
                # raise RuntimeError(
                #     f"Binance ISOLATED limit reached (4/4). "
                #     f"Close one ISOLATED position or use CROSS margin. "
                #     f"Current ISOLATED: {', '.join(isolated_symbols)}"
                # )
            
            self.log.info(f"✅ ISOLATED OK: {len(isolated_open)}/4 positions, allowing {symbol}")
            
        except RuntimeError:
            raise  # Re-raise our own errors
        except Exception as e:
            self.log.warning(f"⚠️ ISOLATED limit check failed: {e} - proceeding anyway (fail-open)")

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
        # Check for GRID trading
        metadata = ticket_exec.get("metadata") or {}
        is_grid = metadata.get("is_grid", False) or ticket_exec.get("is_grid", False)
        
        if is_grid:
            self.log.info(f"🔷 GRID trade detected - executing multi-level grid strategy")
            return await self._execute_grid_trade(ticket_exec)
        
        if flow == "MARKET":
            return await self._execute_trade_direct(ticket_exec)
        elif flow == "HYBRID":
            return await self._execute_trade_hybrid(ticket_exec)
        else:
            raise ValueError(f"Unknown flow: {flow}")

    async def _execute_trade_direct(self, ticket: Dict[str, Any]) -> Dict[str, Any]:
        """
        Direct execution with smart order type selection (LIMIT or MARKET).
        
        Uses LIMIT orders when:
        - entry price is provided in ticket
        - market is trending (not volatile)
        
        Falls back to MARKET when:
        - no entry price
        - volatile market conditions
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
            entry_price = ticket.get("entry") or ticket.get("entry_price") or ticket.get("limit_price")
            
            if not (symbol and side in ("BUY", "SELL") and qty > 0 and leverage > 0):
                return {"ok": False, "error": "bad_ticket_params"}

            try:
                client.futures_change_leverage(symbol=symbol, leverage=leverage)
            except Exception as e:
                self.log.warning(f"futures_change_leverage failed: {e}")

            from utils.order_ids import build_client_order_id
            from utils.trade_execution_core import _q_price
            
            # Determine order type: LIMIT if entry_price provided, otherwise MARKET
            order_type = "LIMIT" if entry_price and float(entry_price) > 0 else "MARKET"
            
            base_kwargs: Dict[str, Any] = {
                "symbol": symbol,
                "side": side,
                "type": order_type,
                "quantity": qty,
                "newClientOrderId": build_client_order_id(symbol, side, role="ENTRY"),
            }
            
            # Add price for LIMIT orders
            if order_type == "LIMIT":
                base_kwargs["price"] = _q_price(symbol, float(entry_price))
                base_kwargs["timeInForce"] = "GTC"
                self.log.info(f"Using LIMIT order @ {entry_price} for {symbol}")
            else:
                self.log.info(f"Using MARKET order for {symbol}")

            pos_side_supplied = str(ticket.get("position_side") or ticket.get("positionSide") or "").upper()
            attempt_order = dict(base_kwargs)
            if pos_side_supplied:
                attempt_order["positionSide"] = pos_side_supplied
            elif os.getenv("POSITION_MODE_OVERRIDE", "").strip().lower() in ("hedge", "hedged") or \
                 os.getenv("BINANCE_FORCE_HEDGE_MODE", "").strip().lower() in ("1", "true", "yes", "on"):
                attempt_order["positionSide"] = "LONG" if side == "BUY" else "SHORT"

            try:
                order = client.futures_create_order(**attempt_order)
                
                # ⏱️ Track LIMIT orders for timeout monitoring
                if order_type == "LIMIT" and self._timeout_monitor and order:
                    try:
                        order_id = order.get("orderId")
                        if order_id:
                            self._timeout_monitor.track_order(
                                order_id=order_id,
                                symbol=symbol,
                                side=side,
                                quantity=str(qty),
                                order_type="ENTRY",
                                position_side=attempt_order.get("positionSide")
                            )
                            self.log.info(f"⏱️ Tracking LIMIT order {order_id} for timeout")
                    except Exception as track_err:
                        self.log.warning(f"Failed to track order for timeout: {track_err}")
                
                # 🛡️ CRITICAL: Send SL/TP orders immediately after entry
                sl_order = None
                tp_order = None
                sltp_failed = False
                
                # 🔧 FIX: Define position_side BEFORE SL/TP block (for emergency close)
                position_side = attempt_order.get("positionSide") or ("LONG" if side == "BUY" else "SHORT")
                
                try:
                    # Get entry price from order
                    entry_price_actual = float(order.get("avgPrice") or order.get("price") or ticket.get("price") or 0)
                    if entry_price_actual <= 0:
                        # For MARKET orders, get current price
                        from utils.binance_client import get_price
                        entry_price_actual = get_price(symbol) or 0
                    
                    if entry_price_actual <= 0:
                        self.log.error(f"🚨 CRITICAL: Could not determine entry price for {symbol} - CANNOT SET SL/TP")
                        sltp_failed = True
                    else:
                        # Calculate SL/TP using ATR-based logic
                        from utils.sltp import calc_sl_tp_for_symbol
                        from utils.trade_execution_core import _q_price, _q_qty
                        
                        atr = ticket.get("atr") or ticket.get("atr_value")
                        atr_mult = float(os.getenv("SL_ATR_MULT", "1.5"))
                        
                        sl_price, tp_price = calc_sl_tp_for_symbol(
                            symbol=symbol,
                            entry=entry_price_actual,
                            side=position_side,  # 🔧 FIX: Use LONG/SHORT instead of BUY/SELL
                            atr=atr,
                            atr_mult=atr_mult
                        )
                        
                        # 🔧 FIX: Fallback if ATR missing - use 2% SL, 3% TP
                        if not sl_price or sl_price <= 0:
                            fallback_sl_pct = 0.02  # 2% stop loss
                            if position_side == "LONG":
                                sl_price = entry_price_actual * (1 - fallback_sl_pct)
                            else:
                                sl_price = entry_price_actual * (1 + fallback_sl_pct)
                            self.log.warning(f"⚠️ ATR missing for {symbol}, using fallback 2% SL @ {sl_price:.6f}")
                        
                        if not tp_price or tp_price <= 0:
                            fallback_tp_pct = 0.03  # 3% take profit
                            if position_side == "LONG":
                                tp_price = entry_price_actual * (1 + fallback_tp_pct)
                            else:
                                tp_price = entry_price_actual * (1 - fallback_tp_pct)
                            self.log.warning(f"⚠️ ATR missing for {symbol}, using fallback 3% TP @ {tp_price:.6f}")
                        
                        close_side = "SELL" if side == "BUY" else "BUY"
                        
                        # Send STOP_MARKET (SL) order
                        try:
                            sl_kwargs = {
                                "symbol": symbol,
                                "side": close_side,
                                "type": "STOP_MARKET",
                                "quantity": qty,
                                "stopPrice": _q_price(symbol, sl_price),
                                "newClientOrderId": build_client_order_id(symbol, close_side, role="SL"),
                            }
                            if position_side:
                                sl_kwargs["positionSide"] = position_side
                            
                            sl_order = client.futures_create_order(**sl_kwargs)
                            self.log.info(f"✅ SL order placed @ {sl_price:.6f} for {symbol}")
                        except Exception as sl_err:
                            self.log.error(f"🚨 CRITICAL: Failed to place SL order for {symbol}: {sl_err}")
                            sltp_failed = True
                        
                        # Send TAKE_PROFIT_MARKET (TP) order
                        try:
                            tp_kwargs = {
                                "symbol": symbol,
                                "side": close_side,
                                "type": "TAKE_PROFIT_MARKET",
                                "quantity": qty,
                                "stopPrice": _q_price(symbol, tp_price),
                                "newClientOrderId": build_client_order_id(symbol, close_side, role="TP"),
                            }
                            if position_side:
                                tp_kwargs["positionSide"] = position_side
                            
                            tp_order = client.futures_create_order(**tp_kwargs)
                            self.log.info(f"✅ TP order placed @ {tp_price:.6f} for {symbol}")
                        except Exception as tp_err:
                            self.log.error(f"🚨 CRITICAL: Failed to place TP order for {symbol}: {tp_err}")
                            sltp_failed = True
                except Exception as sltp_err:
                    self.log.error(f"🚨 CRITICAL: Failed to set SL/TP for {symbol}: {sltp_err}")
                    sltp_failed = True
                
                # 🔧 FIX: Close position if SL/TP failed (cannot leave unprotected!)
                if sltp_failed:
                    self.log.error(f"🚨 EMERGENCY: SL/TP failed for {symbol} - CANCELING ORDERS & CLOSING POSITION")
                    
                    # 🔧 FIX: Cancel any successfully placed SL/TP orders first (prevent dangling orders)
                    try:
                        from utils.binance_client import futures_cancel_all_orders
                        if sl_order or tp_order:
                            cancelled_count = futures_cancel_all_orders(symbol)
                            self.log.info(f"🗑️ Cancelled {cancelled_count} orders for {symbol} (cleanup before emergency close)")
                    except Exception as cancel_err:
                        self.log.warning(f"⚠️ Failed to cancel orders for {symbol}: {cancel_err}")
                    
                    # Close the just-opened position immediately
                    try:
                        from utils.binance_client import futures_create_order
                        close_side = "SELL" if side == "BUY" else "BUY"
                        close_order = futures_create_order(
                            symbol=symbol,
                            side=close_side,
                            type="MARKET",
                            quantity=qty,
                            positionSide=position_side if position_side else None,
                            newClientOrderId=build_client_order_id(symbol, close_side, role="EMERGENCY_CLOSE")
                        )
                        self.log.warning(f"🚨 Emergency closed {symbol} position (no SL/TP protection available)")
                    except Exception as close_err:
                        self.log.error(f"🚨🚨 CRITICAL: Failed to emergency close {symbol}: {close_err} - MANUAL INTERVENTION REQUIRED!")
                    
                    return {
                        "ok": False,
                        "status": "error",  # 🔧 FIX: Explicit status so open_position doesn't default to "opened"
                        "error": "sltp_protection_failed",
                        "detail": f"Position opened but SL/TP orders failed - position emergency closed!",
                        "order": order,
                    }
                
                return {
                    "ok": True,
                    "exchange": "binance_futures",
                    "order": order,
                    "sl_order": sl_order,
                    "tp_order": tp_order,
                    "status": "opened"
                }
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
                    
                    # 🛡️ CRITICAL: Send SL/TP orders after retry entry
                    sl_order = None
                    tp_order = None
                    sltp_failed = False
                    
                    # 🔧 FIX: Define position_side BEFORE SL/TP block (for emergency close)
                    position_side = retry_kwargs.get("positionSide") or ("LONG" if side == "BUY" else "SHORT")
                    
                    try:
                        entry_price_actual = float(order.get("avgPrice") or order.get("price") or ticket.get("price") or 0)
                        if entry_price_actual <= 0:
                            from utils.binance_client import get_price
                            entry_price_actual = get_price(symbol) or 0
                        
                        if entry_price_actual <= 0:
                            self.log.error(f"🚨 CRITICAL: Could not determine entry price for {symbol} (retry) - CANNOT SET SL/TP")
                            sltp_failed = True
                        else:
                            from utils.sltp import calc_sl_tp_for_symbol
                            from utils.trade_execution_core import _q_price
                            
                            atr = ticket.get("atr") or ticket.get("atr_value")
                            atr_mult = float(os.getenv("SL_ATR_MULT", "1.5"))
                            
                            sl_price, tp_price = calc_sl_tp_for_symbol(
                                symbol=symbol, entry=entry_price_actual, side=position_side,  # 🔧 FIX: LONG/SHORT
                                atr=atr, atr_mult=atr_mult
                            )
                            
                            # 🔧 FIX: Fallback if ATR missing - use 2% SL, 3% TP
                            if not sl_price or sl_price <= 0:
                                fallback_sl_pct = 0.02
                                if position_side == "LONG":
                                    sl_price = entry_price_actual * (1 - fallback_sl_pct)
                                else:
                                    sl_price = entry_price_actual * (1 + fallback_sl_pct)
                                self.log.warning(f"⚠️ ATR missing for {symbol} (retry), using fallback 2% SL @ {sl_price:.6f}")
                            
                            if not tp_price or tp_price <= 0:
                                fallback_tp_pct = 0.03
                                if position_side == "LONG":
                                    tp_price = entry_price_actual * (1 + fallback_tp_pct)
                                else:
                                    tp_price = entry_price_actual * (1 - fallback_tp_pct)
                                self.log.warning(f"⚠️ ATR missing for {symbol} (retry), using fallback 3% TP @ {tp_price:.6f}")
                            
                            close_side = "SELL" if side == "BUY" else "BUY"
                            
                            try:
                                sl_order = client.futures_create_order(
                                    symbol=symbol, side=close_side, type="STOP_MARKET",
                                    quantity=qty, stopPrice=_q_price(symbol, sl_price),
                                    positionSide=position_side,
                                    newClientOrderId=build_client_order_id(symbol, close_side, role="SL")
                                )
                                self.log.info(f"✅ SL order placed @ {sl_price:.6f} for {symbol} (retry)")
                            except Exception as sl_err:
                                self.log.error(f"🚨 CRITICAL: Failed to place SL (retry): {sl_err}")
                                sltp_failed = True
                            
                            try:
                                tp_order = client.futures_create_order(
                                    symbol=symbol, side=close_side, type="TAKE_PROFIT_MARKET",
                                    quantity=qty, stopPrice=_q_price(symbol, tp_price),
                                    positionSide=position_side,
                                    newClientOrderId=build_client_order_id(symbol, close_side, role="TP")
                                )
                                self.log.info(f"✅ TP order placed @ {tp_price:.6f} for {symbol} (retry)")
                            except Exception as tp_err:
                                self.log.error(f"🚨 CRITICAL: Failed to place TP (retry): {tp_err}")
                                sltp_failed = True
                    except Exception as sltp_err:
                        self.log.error(f"🚨 CRITICAL: Failed to set SL/TP after retry: {sltp_err}")
                        sltp_failed = True
                    
                    # 🔧 FIX: Close position if SL/TP failed (retry path)
                    if sltp_failed:
                        self.log.error(f"🚨 EMERGENCY: SL/TP failed for {symbol} (retry) - CANCELING ORDERS & CLOSING POSITION")
                        
                        # 🔧 FIX: Cancel any successfully placed SL/TP orders first
                        try:
                            from utils.binance_client import futures_cancel_all_orders
                            if sl_order or tp_order:
                                cancelled_count = futures_cancel_all_orders(symbol)
                                self.log.info(f"🗑️ Cancelled {cancelled_count} orders for {symbol} (retry cleanup)")
                        except Exception as cancel_err:
                            self.log.warning(f"⚠️ Failed to cancel orders for {symbol}: {cancel_err}")
                        
                        # Close the position
                        try:
                            from utils.binance_client import futures_create_order
                            close_side = "SELL" if side == "BUY" else "BUY"
                            close_order = futures_create_order(
                                symbol=symbol,
                                side=close_side,
                                type="MARKET",
                                quantity=qty,
                                positionSide=position_side if position_side else None,
                                newClientOrderId=build_client_order_id(symbol, close_side, role="EMERGENCY_CLOSE")
                            )
                            self.log.warning(f"🚨 Emergency closed {symbol} position (retry - no SL/TP)")
                        except Exception as close_err:
                            self.log.error(f"🚨🚨 CRITICAL: Failed to emergency close {symbol}: {close_err} - MANUAL INTERVENTION REQUIRED!")
                        
                        return {
                            "ok": False,
                            "status": "error",  # 🔧 FIX: Explicit status
                            "error": "sltp_protection_failed",
                            "detail": f"Position opened (retry) but SL/TP orders failed - position emergency closed!",
                            "order": order,
                        }
                    
                    return {
                        "ok": True, "exchange": "binance_futures", "order": order,
                        "sl_order": sl_order, "tp_order": tp_order,
                        "retry": True, "status": "opened"
                    }
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

    async def _execute_grid_trade(self, ticket: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute GRID strategy - place multiple LIMIT orders across price range.
        
        GRID trading involves:
        - Placing N orders (grid_levels) at different prices
        - Spread across range (grid_min to grid_max)
        - Equal spacing between levels (grid_step_pct)
        - All orders are LIMIT orders (not MARKET)
        
        Example:
        - grid_min=148.65, grid_max=161.69, grid_levels=6
        - Creates 6 LIMIT BUY orders at: 148.65, 151.02, 153.38, 155.75, 158.11, 160.48
        """
        try:
            from utils.binance_client import futures_create_order, set_leverage
            from utils.order_ids import build_client_order_id
            from utils.trade_execution_core import _q_price, _q_qty
        except Exception as e:
            return {"ok": False, "error": "imports_failed", "detail": str(e)}
        
        symbol = str(ticket.get("symbol", "")).upper()
        side = str(ticket.get("side", "")).upper()
        leverage = int(ticket.get("leverage") or 2)
        budget_usd = float(ticket.get("budget_usd") or ticket.get("budget") or 100.0)
        
        # Extract GRID parameters
        metadata = ticket.get("metadata") or {}
        grid_min = float(metadata.get("grid_min") or ticket.get("grid_min") or 0)
        grid_max = float(metadata.get("grid_max") or ticket.get("grid_max") or 0)
        grid_levels = int(metadata.get("grid_levels") or ticket.get("grid_levels") or 6)
        
        if not (symbol and side in ("BUY", "SELL") and grid_min > 0 and grid_max > grid_min):
            return {"ok": False, "error": "invalid_grid_params"}
        
        self.log.info(f"🔷 GRID Strategy: {symbol} {side} - {grid_levels} levels from {grid_min} to {grid_max}")
        
        # Set leverage
        try:
            set_leverage(symbol, leverage)
        except Exception as e:
            self.log.warning(f"set_leverage failed: {e}")
        
        # Calculate price levels (equal spacing)
        price_step = (grid_max - grid_min) / (grid_levels - 1) if grid_levels > 1 else 0
        prices = [grid_min + (i * price_step) for i in range(grid_levels)]
        
        # 🛡️ SMART GRID: Ensure each level meets Binance minNotional ($25 per order - DYNAMIC BUDGET v2.0)
        from utils.budget import MIN_BUDGET
        MIN_NOTIONAL_USD = MIN_BUDGET  # Dynamic: $25 minimum (was $100 hardcoded)
        budget_per_level = budget_usd / grid_levels
        
        # CRITICAL: Check if total budget is sufficient for even 1 order
        if budget_usd < MIN_NOTIONAL_USD:
            return {
                "ok": False,
                "status": "error",
                "error": "grid_budget_too_low",
                "detail": f"Budget ${budget_usd:.2f} < ${MIN_NOTIONAL_USD} minNotional requirement. Need at least ${MIN_NOTIONAL_USD}.",
            }
        
        if budget_per_level < MIN_NOTIONAL_USD:
            adjusted_levels = max(1, int(budget_usd / MIN_NOTIONAL_USD))
            self.log.warning(
                f"⚠️ GRID budget too low for {grid_levels} levels "
                f"(${budget_per_level:.2f}/level < ${MIN_NOTIONAL_USD} minNotional). "
                f"Reducing to {adjusted_levels} levels to meet Binance requirements."
            )
            grid_levels = adjusted_levels
            price_step = (grid_max - grid_min) / (grid_levels - 1) if grid_levels > 1 else 0
            prices = [grid_min + (i * price_step) for i in range(grid_levels)]
            budget_per_level = budget_usd / grid_levels
        
        # Place LIMIT orders at each level
        grid_orders = []
        errors = []
        
        for i, price in enumerate(prices, start=1):
            try:
                # Calculate qty for this level: (budget_per_level * leverage) / price
                qty_raw = (budget_per_level * leverage) / price
                qty_str = _q_qty(symbol, qty_raw)
                price_str = _q_price(symbol, price)
                
                order_kwargs = {
                    "symbol": symbol,
                    "side": side,
                    "type": "LIMIT",
                    "timeInForce": "GTC",
                    "quantity": qty_str,
                    "price": price_str,
                    "newClientOrderId": build_client_order_id(symbol, side, role=f"GRID{i}"),
                }
                
                # Add position side if hedge mode
                if os.getenv("POSITION_MODE_OVERRIDE", "").lower() in ("hedge", "hedged"):
                    order_kwargs["positionSide"] = "LONG" if side == "BUY" else "SHORT"
                
                self.log.info(f"  Level {i}/{grid_levels}: LIMIT {side} @ {price_str} qty={qty_str}")
                
                order_result = futures_create_order(**order_kwargs)
                grid_orders.append({
                    "level": i,
                    "price": price,
                    "qty": qty_str,
                    "order": order_result
                })
                
            except Exception as e:
                error_msg = f"Level {i} failed: {e}"
                self.log.error(f"  ❌ {error_msg}")
                errors.append(error_msg)
        
        if not grid_orders:
            return {
                "ok": False,
                "status": "error",
                "error": "all_grid_orders_failed",
                "detail": errors,
            }
        
        self.log.info(f"✅ GRID execution complete: {len(grid_orders)}/{grid_levels} orders placed")
        
        return {
            "ok": True,
            "status": "opened",
            "symbol": symbol,
            "side": side,
            "grid_orders": grid_orders,
            "grid_levels_placed": len(grid_orders),
            "grid_levels_total": grid_levels,
            "errors": errors if errors else None,
            "entry_price": sum(prices) / len(prices) if prices else 0,  # Average price
            "actual_investment": budget_usd,
            "leverage": leverage,
        }
