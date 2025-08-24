# utils/binance_trader.py
from __future__ import annotations
import os, logging
from typing import Dict, Any, Optional
from binance.client import Client
from binance.exceptions import BinanceAPIException, BinanceRequestException

logger = logging.getLogger("algogpt.trader")

# --- ENV ---
BINANCE_API_KEY = (os.getenv("BINANCE_API_KEY") or "").strip()
BINANCE_API_SECRET = (os.getenv("BINANCE_API_SECRET") or "").strip()
USE_TESTNET = (os.getenv("BINANCE_TESTNET", "false").lower() in ("1", "true", "yes"))
SKIP_MUTATIONS = (os.getenv("BINANCE_SKIP_ACCOUNT_MUTATIONS", "false").lower() in ("1", "true", "yes"))

def get_client() -> Client:
    if not BINANCE_API_KEY or not BINANCE_API_SECRET:
        raise RuntimeError("❌ Binance API key/secret missing in ENV")
    client = Client(api_key=BINANCE_API_KEY, api_secret=BINANCE_API_SECRET)
    if USE_TESTNET:
        logger.warning("⚠️ Using Binance TESTNET endpoints")
        client.API_URL = "https://testnet.binance.vision/api"
        client.FUTURES_URL = "https://testnet.binancefuture.com/fapi/v1"
    return client

# --- FUTURES TRADE EXECUTION ---
async def binance_futures_trade(
    symbol: str,
    side: str,
    budget: float,
    leverage: int = 10,
    dry_run: bool = True
) -> Dict[str, Any]:
    """
    מבצע טרייד Futures אמיתי או DRY_RUN ב־Binance
    """
    client = get_client()
    sym = symbol.upper().strip()
    side = side.upper().strip()

    try:
        # נמשוך מחיר עדכני
        mark_price_data = client.futures_mark_price(symbol=sym)
        price = float(mark_price_data["markPrice"])

        # מחשבים כמות לפי תקציב ולווראג'
        qty = round((budget * leverage) / price, 3)  # דיוק עד 3 ספרות

        if dry_run or SKIP_MUTATIONS:
            logger.info(f"🔎 DRY_RUN → {side} {sym} qty={qty} @ {price} lev={leverage}")
            return {
                "symbol": sym,
                "side": side,
                "qty": qty,
                "entry": price,
                "leverage": leverage,
                "dry_run": True,
            }

        # מגדירים לווארג'
        client.futures_change_leverage(symbol=sym, leverage=leverage)

        # מבצעים טרייד
        order = client.futures_create_order(
            symbol=sym,
            side=side,
            type="MARKET",
            quantity=qty
        )

        logger.info(f"✅ Executed {side} {sym} qty={qty} @ {price}")
        return {
            "symbol": sym,
            "side": side,
            "qty": qty,
            "entry": price,
            "leverage": leverage,
            "order_id": order.get("orderId"),
            "dry_run": False,
        }

    except (BinanceAPIException, BinanceRequestException) as e:
        logger.error(f"❌ Binance API error: {e}")
        raise
    except Exception as e:
        logger.error(f"❌ Unexpected error in trade: {e}")
        raise

# --- FORCE CLOSE ---
def force_close_position(symbol: str) -> Dict[str, Any]:
    """
    סוגר בכוח פוזיציה פתוחה ב־Binance Futures
    """
    client = get_client()
    sym = symbol.upper().strip()

    try:
        positions = client.futures_position_information(symbol=sym)
        if not positions:
            return {"ok": False, "error": f"No open position for {sym}"}

        pos = positions[0]
        amt = float(pos["positionAmt"])
        if amt == 0:
            return {"ok": False, "error": f"No position size for {sym}"}

        side = "SELL" if amt > 0 else "BUY"
        qty = abs(amt)

        order = client.futures_create_order(
            symbol=sym,
            side=side,
            type="MARKET",
            quantity=qty,
            reduceOnly=True
        )
        logger.info(f"🔴 Force-closed {sym} side={side} qty={qty}")
        return {"ok": True, "closed": sym, "side": side, "qty": qty, "order_id": order.get("orderId")}

    except Exception as e:
        logger.error(f"❌ force_close_position error: {e}")
        return {"ok": False, "error": str(e)}































