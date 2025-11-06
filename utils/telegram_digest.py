#!/usr/bin/env python3
# utils/telegram_digest.py
"""
Telegram Digest System - Consolidated Notifications
==================================================
Collects notifications and sends them in batches instead of spamming.

- Health alerts: 3x daily (08:00, 16:00, 00:00 Israel time) + critical immediate
- Trade/PNL reports: Every 30 min (only if SL/TP hit or significant changes)
- Trade completion: Summary for every closed position
"""
import os
import time
import logging
import asyncio
from typing import Dict, Any, List, Optional, Literal
from dataclasses import dataclass, asdict, field
from datetime import datetime
import json
from pathlib import Path

logger = logging.getLogger("algogpt.telegram_digest")

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()
TELEGRAM_ENABLED = os.getenv("TELEGRAM_SEND_ENABLE", "1") == "1" and TELEGRAM_TOKEN and TELEGRAM_CHAT_ID

DIGEST_DIR = Path("data/digest")
DIGEST_DIR.mkdir(parents=True, exist_ok=True)

HEALTH_DIGEST_FILE = DIGEST_DIR / "health_queue.jsonl"
TRADE_DIGEST_FILE = DIGEST_DIR / "trade_queue.jsonl"
COMPLETION_DIGEST_FILE = DIGEST_DIR / "completion_queue.jsonl"


@dataclass
class HealthAlert:
    timestamp: float
    level: Literal["INFO", "WARNING", "CRITICAL"]
    message: str
    details: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class TradeEvent:
    timestamp: float
    symbol: str
    event_type: Literal["SL_HIT", "TP1_HIT", "TP2_HIT", "TP3_HIT", "TP4_HIT", "PARTIAL_FILL", "MANUAL_CLOSE"]
    pnl_usd: Optional[float] = None
    pnl_pct: Optional[float] = None
    price: Optional[float] = None
    details: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class TradeCompletion:
    timestamp: float
    symbol: str
    side: str
    entry_price: float
    exit_price: float
    entry_time: float
    exit_time: float
    pnl_usd: float
    pnl_pct: float
    quantity: float
    leverage: int
    exit_reason: str
    sl_price: Optional[float] = None
    tp_prices: List[float] = field(default_factory=list)
    regime: str = "UNKNOWN"
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class TelegramDigest:
    """Manages consolidated Telegram notifications"""
    
    def __init__(self):
        self.health_queue: List[HealthAlert] = []
        self.trade_queue: List[TradeEvent] = []
        self.completion_queue: List[TradeCompletion] = []
        self._load_queues()
    
    def _load_queues(self):
        """Load pending messages from disk"""
        try:
            if HEALTH_DIGEST_FILE.exists():
                with open(HEALTH_DIGEST_FILE, 'r') as f:
                    for line in f:
                        if line.strip():
                            data = json.loads(line)
                            self.health_queue.append(HealthAlert(**data))
        except Exception as e:
            logger.error(f"Failed to load health queue: {e}")
        
        try:
            if TRADE_DIGEST_FILE.exists():
                with open(TRADE_DIGEST_FILE, 'r') as f:
                    for line in f:
                        if line.strip():
                            data = json.loads(line)
                            self.trade_queue.append(TradeEvent(**data))
        except Exception as e:
            logger.error(f"Failed to load trade queue: {e}")
        
        try:
            if COMPLETION_DIGEST_FILE.exists():
                with open(COMPLETION_DIGEST_FILE, 'r') as f:
                    for line in f:
                        if line.strip():
                            data = json.loads(line)
                            self.completion_queue.append(TradeCompletion(**data))
        except Exception as e:
            logger.error(f"Failed to load completion queue: {e}")
    
    def _save_queues(self):
        """Persist queues to disk"""
        try:
            with open(HEALTH_DIGEST_FILE, 'w') as f:
                for alert in self.health_queue:
                    f.write(json.dumps(alert.to_dict()) + '\n')
        except Exception as e:
            logger.error(f"Failed to save health queue: {e}")
        
        try:
            with open(TRADE_DIGEST_FILE, 'w') as f:
                for event in self.trade_queue:
                    f.write(json.dumps(event.to_dict()) + '\n')
        except Exception as e:
            logger.error(f"Failed to save trade queue: {e}")
        
        try:
            with open(COMPLETION_DIGEST_FILE, 'w') as f:
                for completion in self.completion_queue:
                    f.write(json.dumps(completion.to_dict()) + '\n')
        except Exception as e:
            logger.error(f"Failed to save completion queue: {e}")
    
    def add_health_alert(self, level: Literal["INFO", "WARNING", "CRITICAL"], message: str, details: Optional[Dict[str, Any]] = None):
        """Add health alert to queue"""
        alert = HealthAlert(
            timestamp=time.time(),
            level=level,
            message=message,
            details=details or {}
        )
        self.health_queue.append(alert)
        self._save_queues()
        
        if level == "CRITICAL":
            asyncio.create_task(self._send_critical_alert(alert))
        
        logger.info(f"Health alert queued: {level} - {message}")
    
    def add_trade_event(self, symbol: str, event_type: Literal["SL_HIT", "TP1_HIT", "TP2_HIT", "TP3_HIT", "TP4_HIT", "PARTIAL_FILL", "MANUAL_CLOSE"], pnl_usd: Optional[float] = None, 
                       pnl_pct: Optional[float] = None, price: Optional[float] = None, 
                       details: Optional[Dict[str, Any]] = None):
        """Add trade event to queue"""
        event = TradeEvent(
            timestamp=time.time(),
            symbol=symbol,
            event_type=event_type,
            pnl_usd=pnl_usd,
            pnl_pct=pnl_pct,
            price=price,
            details=details or {}
        )
        self.trade_queue.append(event)
        self._save_queues()
        logger.info(f"Trade event queued: {symbol} - {event_type}")
    
    def add_trade_completion(self, symbol: str, side: str, entry_price: float, exit_price: float,
                            entry_time: float, exit_time: float, pnl_usd: float, pnl_pct: float,
                            quantity: float, leverage: int, exit_reason: str, sl_price: Optional[float] = None,
                            tp_prices: Optional[List[float]] = None, regime: str = "UNKNOWN"):
        """Add trade completion to queue"""
        completion = TradeCompletion(
            timestamp=time.time(),
            symbol=symbol,
            side=side,
            entry_price=entry_price,
            exit_price=exit_price,
            entry_time=entry_time,
            exit_time=exit_time,
            pnl_usd=pnl_usd,
            pnl_pct=pnl_pct,
            quantity=quantity,
            leverage=leverage,
            exit_reason=exit_reason,
            sl_price=sl_price,
            tp_prices=tp_prices or [],
            regime=regime
        )
        self.completion_queue.append(completion)
        self._save_queues()
        
        asyncio.create_task(self._send_completion_summary(completion))
        
        logger.info(f"Trade completion queued: {symbol} - {exit_reason}")
    
    async def _send_critical_alert(self, alert: HealthAlert):
        """Send critical alert immediately"""
        if not TELEGRAM_ENABLED:
            return
        
        try:
            import httpx
            
            text = f"🚨 <b>CRITICAL ALERT</b>\n\n{alert.message}\n\n<i>{datetime.fromtimestamp(alert.timestamp).strftime('%Y-%m-%d %H:%M:%S')}</i>"
            
            payload = {
                "chat_id": TELEGRAM_CHAT_ID,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True
            }
            
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                    json=payload
                )
                if resp.status_code == 200:
                    logger.info(f"Critical alert sent: {alert.message[:50]}")
                else:
                    logger.error(f"Failed to send critical alert: {resp.status_code}")
        except Exception as e:
            logger.error(f"Error sending critical alert: {e}")
    
    async def _send_completion_summary(self, completion: TradeCompletion):
        """Send trade completion summary immediately"""
        if not TELEGRAM_ENABLED:
            return
        
        try:
            import httpx
            
            duration_min = int((completion.exit_time - completion.entry_time) / 60)
            pnl_emoji = "💰" if completion.pnl_usd > 0 else "📉"
            
            text = f"""{pnl_emoji} <b>Trade Closed: {completion.symbol}</b>

<b>Side:</b> {completion.side}
<b>Entry:</b> ${completion.entry_price:.4f} → <b>Exit:</b> ${completion.exit_price:.4f}
<b>Quantity:</b> {completion.quantity} | <b>Leverage:</b> {completion.leverage}x

<b>PnL:</b> ${completion.pnl_usd:.2f} ({completion.pnl_pct:+.2f}%)
<b>Duration:</b> {duration_min} minutes
<b>Exit Reason:</b> {completion.exit_reason}
<b>Regime:</b> {completion.regime}

<i>{datetime.fromtimestamp(completion.timestamp).strftime('%Y-%m-%d %H:%M:%S')}</i>"""
            
            payload = {
                "chat_id": TELEGRAM_CHAT_ID,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True
            }
            
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                    json=payload
                )
                if resp.status_code == 200:
                    logger.info(f"Completion summary sent: {completion.symbol}")
                    self.completion_queue.remove(completion)
                    self._save_queues()
                else:
                    logger.error(f"Failed to send completion summary: {resp.status_code}")
        except Exception as e:
            logger.error(f"Error sending completion summary: {e}")
    
    async def send_health_digest(self):
        """Send consolidated health digest"""
        if not self.health_queue or not TELEGRAM_ENABLED:
            return
        
        try:
            import httpx
            
            critical = [a for a in self.health_queue if a.level == "CRITICAL"]
            warnings = [a for a in self.health_queue if a.level == "WARNING"]
            info = [a for a in self.health_queue if a.level == "INFO"]
            
            text = f"📊 <b>System Health Digest</b>\n\n"
            
            if critical:
                text += f"🚨 <b>Critical:</b> {len(critical)}\n"
                for alert in critical[:3]:
                    text += f"  • {alert.message[:80]}\n"
            
            if warnings:
                text += f"⚠️ <b>Warnings:</b> {len(warnings)}\n"
                for alert in warnings[:3]:
                    text += f"  • {alert.message[:80]}\n"
            
            if info:
                text += f"ℹ️ <b>Info:</b> {len(info)}\n"
            
            text += f"\n<i>{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</i>"
            
            payload = {
                "chat_id": TELEGRAM_CHAT_ID,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True
            }
            
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                    json=payload
                )
                if resp.status_code == 200:
                    logger.info(f"Health digest sent: {len(self.health_queue)} alerts")
                    self.health_queue.clear()
                    self._save_queues()
                else:
                    logger.error(f"Failed to send health digest: {resp.status_code}")
        except Exception as e:
            logger.error(f"Error sending health digest: {e}")
    
    async def send_trade_digest(self):
        """Send consolidated trade/PNL digest (only if there are SL/TP hits)"""
        if not self.trade_queue or not TELEGRAM_ENABLED:
            return
        
        significant_events = [e for e in self.trade_queue if e.event_type in 
                             ["SL_HIT", "TP1_HIT", "TP2_HIT", "TP3_HIT", "TP4_HIT"]]
        
        if not significant_events:
            return
        
        try:
            import httpx
            
            total_pnl = sum(e.pnl_usd for e in significant_events if e.pnl_usd is not None)
            
            text = f"📈 <b>Trade Digest (30min)</b>\n\n"
            text += f"<b>Total PnL:</b> ${total_pnl:.2f}\n"
            text += f"<b>Events:</b> {len(significant_events)}\n\n"
            
            for event in significant_events[:5]:
                pnl_str = f"${event.pnl_usd:.2f}" if event.pnl_usd else "N/A"
                text += f"  • {event.symbol} - {event.event_type}: {pnl_str}\n"
            
            text += f"\n<i>{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</i>"
            
            payload = {
                "chat_id": TELEGRAM_CHAT_ID,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True
            }
            
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                    json=payload
                )
                if resp.status_code == 200:
                    logger.info(f"Trade digest sent: {len(significant_events)} events")
                    self.trade_queue.clear()
                    self._save_queues()
                else:
                    logger.error(f"Failed to send trade digest: {resp.status_code}")
        except Exception as e:
            logger.error(f"Error sending trade digest: {e}")


_digest = TelegramDigest()


def get_digest() -> TelegramDigest:
    """Get global digest instance"""
    return _digest


async def send_health_digest():
    """Send health digest (called by scheduler)"""
    await _digest.send_health_digest()


async def send_trade_digest():
    """Send trade digest (called by scheduler)"""
    await _digest.send_trade_digest()
