"""
Profit-Share Billing Engine
Weekly cycle with 18% of net profit
Auto-suspend if unpaid, auto-unlock on payment
"""

from datetime import datetime, timedelta
from typing import Dict, Optional, List, Any
import redis.asyncio as redis

class ProfitShare:
    """
    Profit-share billing engine
    
    Logic:
    - Weekly cycle
    - Formula: profit * 18%
    - Auto-calculate per symbol & exchange
    - Auto-suspend if unpaid after 24h
    - Auto-unlock on payment
    """
    
    def __init__(self, redis_client: Optional[redis.Redis] = None):
        self.redis = redis_client
        self.billing_key = "billing:current"
        self.history_key = "billing:history"
        
        # Configuration
        self.profit_share_rate = 0.18  # 18%
        self.week_start = 0  # Monday
        self.due_window = 86400  # 24 hours to pay
        self.suspend_on_overdue = True
        
        # State
        self.current_billing: Optional[Dict] = None
        self.suspended = False
        
    async def init(self):
        """Initialize from Redis"""
        if self.redis:
            await self.load_billing()
    
    async def load_billing(self) -> None:
        """Load current billing state"""
        if not self.redis:
            return
        
        billing_data: Dict[Any, Any] = await self.redis.hgetall(self.billing_key)
        if billing_data:
            self.current_billing = {
                'total_profit': float(billing_data.get(b'total_profit', 0)),
                'due_amount': float(billing_data.get(b'due_amount', 0)),
                'paid_amount': float(billing_data.get(b'paid_amount', 0)),
                'week_start': billing_data.get(b'week_start', b'').decode(),
                'due_date': billing_data.get(b'due_date', b'').decode(),
                'paid': billing_data.get(b'paid', b'0') == b'1'
            }
        else:
            await self.create_new_billing()
    
    async def create_new_billing(self):
        """Create new weekly billing"""
        
        now = datetime.utcnow()
        week_start = now - timedelta(days=now.weekday())
        due_date = now + timedelta(seconds=self.due_window)
        
        self.current_billing = {
            'week_start': week_start.isoformat(),
            'due_date': due_date.isoformat(),
            'total_profit': 0.0,
            'due_amount': 0.0,
            'paid_amount': 0.0,
            'paid': False,
            'trades': []
        }
        
        await self.save_billing()
    
    async def save_billing(self):
        """Save billing state to Redis"""
        if not self.redis or not self.current_billing:
            return
        
        await self.redis.hset(self.billing_key, mapping={
            'total_profit': str(self.current_billing['total_profit']),
            'due_amount': str(self.current_billing['due_amount']),
            'paid_amount': str(self.current_billing['paid_amount']),
            'week_start': self.current_billing['week_start'],
            'due_date': self.current_billing['due_date'],
            'paid': '1' if self.current_billing['paid'] else '0'
        })
    
    async def calculate_weekly_profit(self) -> Dict:
        """
        Calculate total profit for current week
        Returns: {total_profit, by_symbol, by_exchange}
        """
        
        if not self.redis:
            return {'total_profit': 0, 'by_symbol': {}, 'by_exchange': {}}
        
        week_trades = await self.redis.lrange("trades:completed:week", 0, -1)
        
        total_profit = 0.0
        by_symbol = {}
        by_exchange = {}
        
        for trade_data in week_trades:
            # Parse trade and extract profit
            try:
                trade = eval(trade_data)  # Simple eval for demo
                profit = float(trade.get('pnl', 0))
                symbol = trade.get('symbol', 'UNKNOWN')
                exchange = trade.get('exchange', 'binance')
                
                total_profit += profit
                by_symbol[symbol] = by_symbol.get(symbol, 0) + profit
                by_exchange[exchange] = by_exchange.get(exchange, 0) + profit
            except:
                pass
        
        return {
            'total_profit': total_profit,
            'by_symbol': by_symbol,
            'by_exchange': by_exchange
        }
    
    async def generate_invoice(self) -> Dict:
        """
        Generate weekly invoice
        
        Format:
        Binance: 10 trades (6/10 win) +$312
        Bybit:   4 trades (3/4 win) +$88
        TOTAL:   +$400
        Due:     $72 (18%)
        """
        
        profit_data = await self.calculate_weekly_profit()
        total_profit = profit_data['total_profit']
        due_amount = max(0, total_profit * self.profit_share_rate)
        
        # Calculate win rate by exchange
        invoice_lines: List[Dict[str, Any]] = []
        
        for exchange, profit in profit_data['by_exchange'].items():
            # Get trade count for this exchange
            if self.redis:
                trades = await self.redis.lrange(f"trades:{exchange}:week", 0, -1)
                win_count = len([t for t in trades if eval(t).get('pnl', 0) > 0])
            else:
                trades = []
                win_count = 0
            
            invoice_lines.append({
                'exchange': exchange,
                'trades': len(trades),
                'wins': win_count,
                'profit': profit
            })
        
        if self.current_billing:
            self.current_billing['total_profit'] = total_profit
            self.current_billing['due_amount'] = due_amount
            
            await self.save_billing()
            
            return {
                'invoice_lines': invoice_lines,
                'total_profit': total_profit,
                'due_amount': due_amount,
                'rate': f"{self.profit_share_rate * 100:.0f}%",
                'due_date': self.current_billing['due_date'],
                'wallet': 'TBD'  # Placeholder
            }
        
        return {
            'invoice_lines': invoice_lines,
            'total_profit': 0.0,
            'due_amount': 0.0,
            'rate': '18%',
            'due_date': '',
            'wallet': 'TBD'
        }
    
    async def mark_paid(self, amount: float) -> bool:
        """
        Mark billing as paid
        Auto-unlock trading if suspended
        """
        
        if not self.current_billing:
            return False
        
        due = self.current_billing['due_amount']
        
        if amount < due:
            return False  # Partial payment not allowed
        
        self.current_billing['paid'] = True
        self.current_billing['paid_amount'] = amount
        
        # Resume trading
        self.suspended = False
        
        if self.redis:
            await self.redis.lpush(
                self.history_key,
                f"PAID {amount} at {datetime.utcnow().isoformat()}"
            )
            await self.redis.delete("billing:suspended")
        
        await self.save_billing()
        return True
    
    async def check_overdue(self) -> bool:
        """Check if billing is overdue"""
        
        if not self.current_billing:
            return False
        
        if self.current_billing['paid']:
            return False  # Already paid
        
        due_date = datetime.fromisoformat(self.current_billing['due_date'])
        
        if datetime.utcnow() > due_date:
            # Overdue - suspend trading
            self.suspended = True
            
            if self.redis:
                await self.redis.set("billing:suspended", "1")
            
            return True
        
        return False
    
    async def get_status(self) -> Dict:
        """Get billing status"""
        
        await self.load_billing()
        overdue = await self.check_overdue()
        
        return {
            'current_billing': self.current_billing if self.current_billing else {},
            'overdue': overdue,
            'suspended': self.suspended,
            'payment_status': 'PAID' if (self.current_billing and self.current_billing.get('paid')) else 'PENDING'
        }


async def get_profit_share(redis_client: Optional[redis.Redis] = None) -> ProfitShare:
    """Get ProfitShare instance"""
    profit_share = ProfitShare(redis_client)
    await profit_share.init()
    return profit_share
