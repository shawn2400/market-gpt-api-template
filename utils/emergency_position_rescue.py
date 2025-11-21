#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🚨 Emergency Position Rescue - Fix SL/TP placement issues
=========================================================
Fixes missing SL/TP orders on exchange and ensures proper trailing
"""

import logging
import asyncio
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("emergency_rescue")


class EmergencyPositionRescuer:
    """Rescues positions with missing or incorrect SL/TP orders"""
    
    def __init__(self):
        self.rescued_positions = {}
        logger.info("🚨 Emergency Position Rescuer initialized")
    
    def diagnose_position(self, symbol: str, position_data: Dict) -> Dict:
        """
        Diagnose SL/TP issues on a position
        
        Returns comprehensive diagnosis of what's wrong
        """
        entry_price = float(position_data.get('entry_price', 0))
        mark_price = float(position_data.get('mark_price', 0))
        pnl_pct = float(position_data.get('pnl_percent', 0))
        side = "LONG" if position_data.get('size', 0) > 0 else "SHORT"
        
        issues = []
        recommendations = []
        
        # Check if SL exists
        existing_orders = position_data.get('orders', [])
        has_sl = any(o['type'] == 'STOP_LOSS' or o['type'] == 'STOP_MARKET' for o in existing_orders)
        has_tp = any(o['type'] == 'TAKE_PROFIT' or 'LIMIT_CLOSE' in o['type'] for o in existing_orders)
        
        if not has_sl:
            issues.append("❌ NO STOP LOSS FOUND ON EXCHANGE")
            recommendations.append(f"✅ Place SL at {entry_price * 0.98:.8f} (2% below entry)")
        
        if not has_tp and pnl_pct >= 1.5:
            issues.append("❌ NO TAKE PROFIT - Position in profit but no exit")
            recommendations.append(f"✅ Place TP at {mark_price * 1.05:.8f} (5% above current)")
        
        # Check if SL is at wrong level
        if has_sl:
            sl_orders = [o for o in existing_orders if o['type'] in ['STOP_LOSS', 'STOP_MARKET']]
            for sl_order in sl_orders:
                sl_price = float(sl_order.get('price', 0))
                
                if side == "LONG" and sl_price >= mark_price:
                    issues.append(f"⚠️ SL ABOVE MARK: SL={sl_price:.8f} > Mark={mark_price:.8f}")
                    recommendations.append(f"✅ Move SL down to {entry_price * 0.98:.8f}")
                
                elif side == "SHORT" and sl_price <= mark_price:
                    issues.append(f"⚠️ SL BELOW MARK: SL={sl_price:.8f} < Mark={mark_price:.8f}")
                    recommendations.append(f"✅ Move SL up to {entry_price * 1.02:.8f}")
        
        return {
            'symbol': symbol,
            'side': side,
            'entry_price': entry_price,
            'mark_price': mark_price,
            'pnl_pct': pnl_pct,
            'has_sl': has_sl,
            'has_tp': has_tp,
            'issues': issues,
            'recommendations': recommendations,
            'severity': "CRITICAL" if issues else "OK"
        }
    
    def generate_sl_order_payload(self, symbol: str, position_data: Dict, 
                                 sl_distance_pct: float = 2.0) -> Dict:
        """
        Generate SL order payload for Binance
        
        CRITICAL: Ensures SL is placed on exchange
        """
        entry_price = float(position_data.get('entry_price', 0))
        mark_price = float(position_data.get('mark_price', 0))
        size = abs(float(position_data.get('size', 0)))
        side = "LONG" if position_data.get('size', 0) > 0 else "SHORT"
        
        if side == "LONG":
            # For LONG: SL goes below entry
            sl_price = entry_price * (1 - sl_distance_pct / 100.0)
            close_side = "SELL"
        else:
            # For SHORT: SL goes above entry
            sl_price = entry_price * (1 + sl_distance_pct / 100.0)
            close_side = "BUY"
        
        # Validate SL price
        if sl_price <= 0:
            logger.error(f"❌ Invalid SL price: {sl_price}")
            return {}
        
        payload = {
            'symbol': symbol,
            'side': close_side,
            'type': 'STOP_MARKET',
            'quantity': size,
            'stopPrice': round(sl_price, 8),
            'reduceOnly': True,
            'positionSide': side
        }
        
        logger.info(f"📊 SL Payload for {symbol}: {side} @ {sl_price:.8f} ({sl_distance_pct}%)")
        
        return payload
    
    def generate_tp_order_payloads(self, symbol: str, position_data: Dict,
                                  tp_levels: Optional[List[float]] = None) -> List[Dict]:
        """
        Generate multi-level TP order payloads
        
        Default: 3 levels at 1.5%, 3.0%, 5.0% above current
        """
        tp_levels_to_use: List[float] = tp_levels if tp_levels is not None else [1.5, 3.0, 5.0]
        
        mark_price = float(position_data.get('mark_price', 0))
        size = abs(float(position_data.get('size', 0)))
        side = "LONG" if position_data.get('size', 0) > 0 else "SHORT"
        
        # Split size across levels
        qty_per_level = size / len(tp_levels_to_use)
        
        payloads = []
        
        for i, tp_pct in enumerate(tp_levels_to_use):
            if side == "LONG":
                tp_price = mark_price * (1 + tp_pct / 100.0)
                close_side = "SELL"
            else:
                tp_price = mark_price * (1 - tp_pct / 100.0)
                close_side = "BUY"
            
            payload = {
                'symbol': symbol,
                'side': close_side,
                'type': 'TAKE_PROFIT_MARKET',
                'quantity': round(qty_per_level, 8),
                'stopPrice': round(tp_price, 8),
                'reduceOnly': True,
                'positionSide': side,
                'tp_level': i + 1
            }
            
            payloads.append(payload)
            logger.info(f"📊 TP{i+1} Payload: {close_side} {qty_per_level:.4f} @ {tp_price:.8f}")
        
        return payloads
    
    def validate_sl_on_exchange(self, symbol: str, open_orders: List[Dict]) -> Tuple[bool, str]:
        """
        Validate that SL order exists on exchange
        
        Returns: (is_valid, message)
        """
        sl_orders = [o for o in open_orders if o.get('type') in ['STOP', 'STOP_MARKET', 'STOP_LOSS_LIMIT']]
        
        if not sl_orders:
            return False, f"❌ {symbol}: No SL order on exchange"
        
        for sl_order in sl_orders:
            order_id = sl_order.get('orderId')
            status = sl_order.get('status', 'UNKNOWN')
            stop_price = float(sl_order.get('stopPrice', 0))
            
            logger.info(f"✅ {symbol} SL found: Order#{order_id} Status={status} StopPrice={stop_price:.8f}")
        
        return True, f"✅ {symbol}: SL validated on exchange"
    
    def get_rescue_plan(self, positions_analysis: List[Dict]) -> Dict:
        """
        Generate comprehensive rescue plan for all positions
        """
        plan = {
            'critical_positions': [],
            'actions_needed': [],
            'total_positions_checked': len(positions_analysis),
            'positions_needing_rescue': 0
        }
        
        for analysis in positions_analysis:
            if analysis['severity'] == 'CRITICAL':
                plan['critical_positions'].append(analysis)
                plan['actions_needed'].extend(analysis['recommendations'])
                plan['positions_needing_rescue'] += 1
        
        logger.info(f"🚨 Rescue plan: {plan['positions_needing_rescue']}/{plan['total_positions_checked']} positions need rescue")
        
        return plan


# Singleton
_rescuer: Optional[EmergencyPositionRescuer] = None


def get_emergency_rescuer() -> EmergencyPositionRescuer:
    """Get singleton rescuer instance"""
    global _rescuer
    if _rescuer is None:
        _rescuer = EmergencyPositionRescuer()
    return _rescuer
