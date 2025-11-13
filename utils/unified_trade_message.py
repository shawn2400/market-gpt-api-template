#!/usr/bin/env python3
# utils/unified_trade_message.py
"""
Unified Trade Message System
Single message per symbol that updates from Entry → Opened → Closed
"""
import logging
from typing import Dict, Any, Optional
from utils.telegram_api import send_message, edit_message
from utils.unified_telegram_tracker import get_tracker

logger = logging.getLogger("unified_trade_msg")

async def send_unified_entry_message(
    symbol: str,
    chat_id: int,
    entry_text: str,
    reply_markup: Optional[Dict[str, Any]] = None
) -> Optional[int]:
    """
    Send entry message and track message_id
    Returns message_id if successful
    """
    try:
        response = await send_message(
            chat_id=chat_id,
            text=entry_text,
            reply_markup=reply_markup,
            parse_mode="HTML"
        )
        
        if response.get("ok") and "result" in response:
            message_id = response["result"]["message_id"]
            
            # Track message
            get_tracker().register_entry(symbol, message_id, chat_id, {
                "entry_text": entry_text[:200]  # Store excerpt
            })
            
            logger.info(f"Sent unified entry for {symbol}, msg_id={message_id}")
            return message_id
        else:
            logger.error(f"Failed to send entry for {symbol}: {response}")
            return None
            
    except Exception as e:
        logger.error(f"Error sending unified entry for {symbol}: {e}")
        return None


async def update_unified_opened_message(
    symbol: str,
    open_data: Dict[str, Any]
) -> bool:
    """
    Update message to show "OPENED" status
    """
    try:
        tracked = get_tracker().get_message(symbol)
        if not tracked:
            logger.warning(f"No tracked message for {symbol}, cannot update to OPENED")
            return False
        
        message_id = tracked["message_id"]
        chat_id = tracked["chat_id"]
        
        # Build updated text
        entry_text = tracked.get("entry_data", {}).get("entry_text", "")
        
        opened_section = f"\n\n✅ <b>OPENED</b>\n"
        opened_section += f"  • Price: <code>{open_data.get('price', 'N/A')}</code>\n"
        opened_section += f"  • Qty: <code>{open_data.get('qty', 'N/A')}</code>\n"
        opened_section += f"  • Leverage: <b>{open_data.get('leverage', 'N/A')}</b>x"
        
        updated_text = entry_text + opened_section
        
        # Edit message
        response = await edit_message(
            chat_id=chat_id,
            message_id=message_id,
            text=updated_text,
            parse_mode="HTML"
        )
        
        if response.get("ok"):
            get_tracker().update_opened(symbol, open_data)
            logger.info(f"Updated {symbol} to OPENED, msg_id={message_id}")
            return True
        else:
            logger.error(f"Failed to update {symbol} to OPENED: {response}")
            return False
            
    except Exception as e:
        logger.error(f"Error updating {symbol} to OPENED: {e}")
        return False


async def update_unified_closed_message(
    symbol: str,
    close_data: Dict[str, Any]
) -> bool:
    """
    Update message to show "CLOSED" status with PnL
    """
    try:
        tracked = get_tracker().get_message(symbol)
        if not tracked:
            logger.warning(f"No tracked message for {symbol}, cannot update to CLOSED")
            return False
        
        message_id = tracked["message_id"]
        chat_id = tracked["chat_id"]
        
        # Build final text
        entry_text = tracked.get("entry_data", {}).get("entry_text", "")
        
        pnl_usd = close_data.get("pnl_usd", 0.0)
        pnl_pct = close_data.get("pnl_pct", 0.0)
        duration_min = close_data.get("duration_min", 0)
        exit_reason = close_data.get("exit_reason", "UNKNOWN")
        
        pnl_emoji = "💰" if pnl_usd > 0 else "📉"
        
        closed_section = f"\n\n{pnl_emoji} <b>CLOSED</b>\n"
        closed_section += f"  • PnL: <b>${pnl_usd:.2f}</b> ({pnl_pct:+.2f}%)\n"
        closed_section += f"  • Duration: {duration_min} min\n"
        closed_section += f"  • Exit Reason: {exit_reason}"
        
        updated_text = entry_text + closed_section
        
        # Edit message  
        response = await edit_message(
            chat_id=chat_id,
            message_id=message_id,
            text=updated_text,
            parse_mode="HTML"
        )
        
        if response.get("ok"):
            get_tracker().update_closed(symbol, close_data)
            # Remove from tracker after 1 hour
            logger.info(f"Updated {symbol} to CLOSED, msg_id={message_id}")
            return True
        else:
            logger.error(f"Failed to update {symbol} to CLOSED: {response}")
            return False
            
    except Exception as e:
        logger.error(f"Error updating {symbol} to CLOSED: {e}")
        return False

