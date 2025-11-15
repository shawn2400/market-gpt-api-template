# utils/dynamic_combo_engine.py
"""
🤖 Dynamic Combo Generator - AI that creates and evolves indicator combinations
Learns from performance, adapts weights, and removes failing combos
"""

from __future__ import annotations
import os
import time
import random
import logging
import json
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, asdict
from enum import Enum
from datetime import datetime, timedelta

logger = logging.getLogger("algogpt.dynamic_combo")


class ComboType(Enum):
    """סוג הקומבו"""
    TREND_FOLLOWING = "trend_following"
    MEAN_REVERSION = "mean_reversion"
    BREAKOUT = "breakout"
    MOMENTUM = "momentum"
    HYBRID = "hybrid"


@dataclass
class IndicatorConfig:
    """הגדרת אינדיקטור בקומבו"""
    name: str
    weight: float  # 0-1
    params: Dict[str, Any]
    condition: str  # 'above', 'below', 'cross', 'range'


@dataclass
class DynamicCombo:
    """קומבו דינמי שנוצר ע"י ה-AI"""
    id: str
    name: str
    combo_type: ComboType
    indicators: List[IndicatorConfig]
    conditions: List[str]
    performance: Dict[str, float]
    created_at: float
    updated_at: float
    active: bool = True
    total_trades: int = 0


class DynamicComboGenerator:
    """
    🧠 מנוע ליצירה אוטומטית ודינמית של שילובי אינדיקטורים
    
    Features:
    - יוצר קומבויים חדשים based on market regime
    - לומד מהיסטוריית ביצועים
    - מתאים משקולות אוטומטית
    - מבצע אבולוציה (מחליף אינדיקטורים כושלים)
    - מוחק קומבויים עם ביצועים גרועים
    """
    
    def __init__(self, storage_path: str = "data/dynamic_combos.json"):
        self.storage_path = storage_path
        self.active_combos: Dict[str, DynamicCombo] = {}
        self.performance_history: Dict[str, List[Dict]] = {}
        self.learning_rate = 0.1
        
        # Ensure data directory exists
        import os
        os.makedirs(os.path.dirname(storage_path), exist_ok=True)
        
        # מאגר אינדיקטורים זמין
        self.indicator_pool = {
            'trend': ['EMA_9', 'EMA_20', 'EMA_50', 'EMA_100', 'ADX', 'MACD', 'VWAP'],
            'momentum': ['RSI', 'Stochastic', 'CCI', 'ROC', 'MFI'],
            'volatility': ['ATR', 'Bollinger_Bands', 'Keltner_Channels', 'Standard_Dev'],
            'volume': ['Volume', 'OBV', 'Volume_Profile', 'VWAP'],
            'support_resistance': ['Pivot_Points', 'Fibonacci', 'Dynamic_SR']
        }
        
        # טען combos קיימים
        self._load_combos()
        
        # אם אין combos, צור ברירות מחדל
        if not self.active_combos:
            self._initialize_default_combos()
    
    def _load_combos(self):
        """טוען קומבויים שמורים מהדיסק"""
        try:
            if os.path.exists(self.storage_path):
                with open(self.storage_path, 'r') as f:
                    data = json.load(f)
                    for combo_id, combo_data in data.get('combos', {}).items():
                        # Reconstruct combo object
                        combo_data['combo_type'] = ComboType(combo_data['combo_type'])
                        indicators = []
                        for ind_data in combo_data['indicators']:
                            indicators.append(IndicatorConfig(**ind_data))
                        combo_data['indicators'] = indicators
                        self.active_combos[combo_id] = DynamicCombo(**combo_data)
                    
                    self.performance_history = data.get('performance_history', {})
                    logger.info(f"✅ Loaded {len(self.active_combos)} dynamic combos from storage")
        except Exception as e:
            logger.warning(f"Failed to load combos from storage: {e}")
    
    def _save_combos(self):
        """שומר קומבויים לדיסק"""
        try:
            data = {
                'combos': {},
                'performance_history': self.performance_history,
                'last_updated': time.time()
            }
            
            for combo_id, combo in self.active_combos.items():
                combo_dict = asdict(combo)
                combo_dict['combo_type'] = combo.combo_type.value
                data['combos'][combo_id] = combo_dict
            
            with open(self.storage_path, 'w') as f:
                json.dump(data, f, indent=2)
            
            logger.debug(f"💾 Saved {len(self.active_combos)} combos to storage")
        except Exception as e:
            logger.warning(f"Failed to save combos: {e}")
    
    def _initialize_default_combos(self):
        """מאתחל קומבויים בסיסיים"""
        logger.info("🎯 Initializing default dynamic combos...")
        
        # Default combo 1: Trend + Momentum
        combo1 = DynamicCombo(
            id=self._generate_combo_id(),
            name="AI Trend + Momentum",
            combo_type=ComboType.TREND_FOLLOWING,
            indicators=[
                IndicatorConfig("EMA_20", 0.3, {'period': 20}, 'above'),
                IndicatorConfig("EMA_50", 0.3, {'period': 50}, 'above'),
                IndicatorConfig("RSI", 0.2, {'period': 14}, 'range'),
                IndicatorConfig("MACD", 0.2, {}, 'positive')
            ],
            conditions=[
                "EMA_20 > EMA_50",
                "RSI BETWEEN 30 AND 70",
                "MACD histogram > 0",
                "Volume > SMA(Volume, 20)"
            ],
            performance={'win_rate': 0.0, 'profit_factor': 0.0, 'sharpe': 0.0},
            created_at=time.time(),
            updated_at=time.time()
        )
        self.active_combos[combo1.id] = combo1
        
        # Default combo 2: Breakout
        combo2 = DynamicCombo(
            id=self._generate_combo_id(),
            name="AI Breakout + Volume",
            combo_type=ComboType.BREAKOUT,
            indicators=[
                IndicatorConfig("Bollinger_Bands", 0.4, {'period': 20, 'std': 2}, 'break_upper'),
                IndicatorConfig("Volume", 0.3, {}, 'above_avg'),
                IndicatorConfig("RSI", 0.2, {'period': 14}, 'below_70'),
                IndicatorConfig("ATR", 0.1, {'period': 14}, 'high_volatility')
            ],
            conditions=[
                "Price > Bollinger_Upper OR Price < Bollinger_Lower",
                "Volume > 1.5 * SMA(Volume, 20)",
                "RSI < 70 (for longs) OR RSI > 30 (for shorts)",
                "ATR > SMA(ATR, 14)"
            ],
            performance={'win_rate': 0.0, 'profit_factor': 0.0, 'sharpe': 0.0},
            created_at=time.time(),
            updated_at=time.time()
        )
        self.active_combos[combo2.id] = combo2
        
        self._save_combos()
        logger.info(f"✅ Initialized {len(self.active_combos)} default combos")
    
    def _generate_combo_id(self) -> str:
        """מייצר ID ייחודי לקומבו"""
        timestamp = int(time.time() * 1000)
        random_suffix = random.randint(1000, 9999)
        return f"DYN_{timestamp}_{random_suffix}"
    
    def generate_dynamic_combo(
        self,
        market_regime: str,
        success_patterns: Optional[List[Dict]] = None
    ) -> DynamicCombo:
        """
        🎯 יוצר קומבו חדש dynamically based on מצב שוק ודפוסי הצלחה
        
        Args:
            market_regime: 'trending', 'ranging', 'volatile', 'breakout'
            success_patterns: דפוסים מוצלחים מהעבר
        
        Returns:
            DynamicCombo חדש
        """
        combo_id = self._generate_combo_id()
        
        # בחירת אינדיקטורים based on market regime
        selected_indicators = self._select_indicators_for_regime(market_regime)
        
        # יצירת תנאים based on אינדיקטורים
        conditions = self._generate_conditions(selected_indicators, success_patterns or [])
        
        # קביעת סוג הקומבו
        combo_type = self._detect_combo_type(selected_indicators, market_regime)
        
        new_combo = DynamicCombo(
            id=combo_id,
            name=f"AI {market_regime.title()} Combo {combo_id[-4:]}",
            combo_type=combo_type,
            indicators=selected_indicators,
            conditions=conditions,
            performance={'win_rate': 0.5, 'profit_factor': 1.0, 'sharpe': 0.0},
            created_at=time.time(),
            updated_at=time.time()
        )
        
        self.active_combos[combo_id] = new_combo
        self._save_combos()
        
        logger.info(f"🎯 Created new dynamic combo: {new_combo.name} (regime={market_regime})")
        return new_combo
    
    def _select_indicators_for_regime(self, regime: str) -> List[IndicatorConfig]:
        """בוחר אינדיקטורים מתאימים based on סוג השוק"""
        
        regime_indicators = {
            'trending': ['EMA_20', 'EMA_50', 'ADX', 'MACD', 'ATR'],
            'ranging': ['Bollinger_Bands', 'RSI', 'Stochastic', 'Support_Resistance'],
            'volatile': ['ATR', 'Bollinger_Bands', 'Standard_Dev', 'Volume'],
            'breakout': ['Bollinger_Bands', 'Volume', 'VWAP', 'RSI', 'ATR']
        }
        
        selected_names = regime_indicators.get(regime, ['EMA_20', 'RSI', 'Volume', 'ATR'])
        selected_indicators = []
        
        # לוקח עד 4 אינדיקטורים
        for indicator_name in selected_names[:4]:
            config = IndicatorConfig(
                name=indicator_name,
                weight=0.25,  # weight אחיד בהתחלה
                params=self._get_default_params(indicator_name),
                condition=self._get_default_condition(indicator_name)
            )
            selected_indicators.append(config)
        
        return selected_indicators
    
    def _get_default_params(self, indicator_name: str) -> Dict[str, Any]:
        """מחזיר פרמטרים default לאינדיקטור"""
        params_map = {
            'EMA_20': {'period': 20},
            'EMA_50': {'period': 50},
            'RSI': {'period': 14},
            'MACD': {'fast': 12, 'slow': 26, 'signal': 9},
            'ATR': {'period': 14},
            'Bollinger_Bands': {'period': 20, 'std': 2},
            'ADX': {'period': 14}
        }
        return params_map.get(indicator_name, {})
    
    def _get_default_condition(self, indicator_name: str) -> str:
        """מחזיר condition default based on סוג האינדיקטור"""
        conditions_map = {
            'EMA_20': 'above',
            'EMA_50': 'above',
            'RSI': 'range',
            'MACD': 'positive',
            'Volume': 'above_avg',
            'Bollinger_Bands': 'break',
            'ADX': 'above_25',
            'ATR': 'high_volatility'
        }
        return conditions_map.get(indicator_name, 'above')
    
    def _generate_conditions(
        self,
        indicators: List[IndicatorConfig],
        success_patterns: List[Dict]
    ) -> List[str]:
        """מייצר תנאים based on אינדיקטורים"""
        conditions = []
        
        for indicator in indicators:
            if indicator.name.startswith('EMA'):
                conditions.append(f"{indicator.name} > EMA_50")
            elif indicator.name == 'RSI':
                conditions.append("RSI BETWEEN 30 AND 70")
            elif indicator.name == 'Volume':
                conditions.append("Volume > SMA(Volume, 20)")
            elif indicator.name == 'Bollinger_Bands':
                conditions.append("Price breaks Bollinger Band")
            elif indicator.name == 'MACD':
                conditions.append("MACD histogram positive")
            elif indicator.name == 'ADX':
                conditions.append("ADX > 25 (strong trend)")
        
        return conditions
    
    def _detect_combo_type(
        self,
        indicators: List[IndicatorConfig],
        regime: str
    ) -> ComboType:
        """מזהה סוג קומבו based on אינדיקטורים"""
        indicator_names = {ind.name for ind in indicators}
        
        if regime == 'trending' or any('EMA' in name for name in indicator_names):
            return ComboType.TREND_FOLLOWING
        elif regime == 'breakout' or 'Bollinger_Bands' in indicator_names:
            return ComboType.BREAKOUT
        elif 'RSI' in indicator_names or 'Stochastic' in indicator_names:
            return ComboType.MOMENTUM
        else:
            return ComboType.HYBRID
    
    def evaluate_combo_performance(
        self,
        combo_id: str,
        trade_results: List[Dict[str, Any]]
    ):
        """
        📊 מעריך ומעדכן ביצועי קומבו
        
        Args:
            combo_id: ID של הקומבו
            trade_results: רשימת עסקאות עם תוצאות
                [{'pnl': 100, 'win': True, 'exit_reason': 'tp'}, ...]
        """
        if combo_id not in self.active_combos:
            logger.warning(f"Combo {combo_id} not found")
            return
        
        combo = self.active_combos[combo_id]
        
        if not trade_results:
            logger.warning(f"No trade results for combo {combo_id}")
            return
        
        # חישוב מדדים
        wins = [t for t in trade_results if t.get('pnl', 0) > 0]
        losses = [t for t in trade_results if t.get('pnl', 0) < 0]
        
        win_rate = len(wins) / len(trade_results) if trade_results else 0
        
        total_profit = sum([t['pnl'] for t in wins])
        total_loss = abs(sum([t['pnl'] for t in losses]))
        profit_factor = total_profit / total_loss if total_loss > 0 else 1.0
        
        # עדכון הביצועים
        combo.performance.update({
            'win_rate': win_rate,
            'profit_factor': profit_factor,
            'total_trades': len(trade_results),
            'avg_win': total_profit / len(wins) if wins else 0,
            'avg_loss': total_loss / len(losses) if losses else 0
        })
        combo.total_trades = len(trade_results)
        combo.updated_at = time.time()
        
        # שמור בהיסטוריה
        if combo_id not in self.performance_history:
            self.performance_history[combo_id] = []
        
        self.performance_history[combo_id].append({
            'timestamp': time.time(),
            'win_rate': win_rate,
            'profit_factor': profit_factor,
            'total_trades': len(trade_results)
        })
        
        # התאמת משקולות based on ביצועים
        self._adjust_combo_weights(combo_id, win_rate, profit_factor)
        
        self._save_combos()
        
        logger.info(f"📊 Updated combo {combo_id}: WR={win_rate:.2%}, PF={profit_factor:.2f}")
    
    def _adjust_combo_weights(self, combo_id: str, win_rate: float, profit_factor: float):
        """מתאים את משקולות האינדיקטורים based on ביצועים"""
        combo = self.active_combos[combo_id]
        
        # ציון כולל של הביצועים
        performance_score = (win_rate + min(profit_factor, 3)) / 2
        
        if performance_score > 0.6:
            # ביצועים טובים - הגדל משקולות
            for indicator in combo.indicators:
                indicator.weight *= (1 + self.learning_rate)
            logger.debug(f"📈 Increasing weights for combo {combo_id} (score={performance_score:.2f})")
            
        elif performance_score < 0.4 and combo.total_trades > 20:
            # ביצועים גרועים - evolve או remove
            logger.warning(f"📉 Poor performance for combo {combo_id} (score={performance_score:.2f})")
            self._evolve_or_remove_combo(combo_id)
        
        # נורמליזציה של משקולות
        total_weight = sum(ind.weight for ind in combo.indicators)
        if total_weight > 0:
            for indicator in combo.indicators:
                indicator.weight /= total_weight
    
    def _evolve_or_remove_combo(self, combo_id: str):
        """מפתח קומבו חדש או מסיר קומבו כושל"""
        combo = self.active_combos[combo_id]
        
        if combo.total_trades > 30 and combo.performance.get('win_rate', 0) < 0.35:
            # הסר קומבו כושל לחלוטין
            del self.active_combos[combo_id]
            self._save_combos()
            logger.warning(f"🗑️ Removed combo {combo_id} due to poor performance (WR<35%)")
        else:
            # evolve - החלף אינדיקטור אחד
            self._evolve_combo(combo_id)
    
    def _evolve_combo(self, combo_id: str):
        """מפתח קומבו קיים על ידי החלפת אינדיקטור"""
        combo = self.active_combos[combo_id]
        
        # מצא את האינדיקטור עם המשקל הנמוך ביותר
        if not combo.indicators:
            return
        
        worst_indicator = min(combo.indicators, key=lambda x: x.weight)
        
        # החלף באינדיקטור אקראי אחר
        all_indicators = []
        for category_indicators in self.indicator_pool.values():
            all_indicators.extend(category_indicators)
        
        # סינון אינדיקטורים קיימים
        current_indicators = {ind.name for ind in combo.indicators}
        available_indicators = [ind for ind in all_indicators if ind not in current_indicators]
        
        if available_indicators:
            new_indicator_name = random.choice(available_indicators)
            new_indicator = IndicatorConfig(
                name=new_indicator_name,
                weight=0.25,
                params=self._get_default_params(new_indicator_name),
                condition=self._get_default_condition(new_indicator_name)
            )
            
            # החלף
            combo.indicators.remove(worst_indicator)
            combo.indicators.append(new_indicator)
            combo.updated_at = time.time()
            
            self._save_combos()
            logger.info(f"🧬 Evolved combo {combo_id}: {worst_indicator.name} → {new_indicator_name}")
    
    def get_active_combos(self) -> List[DynamicCombo]:
        """מחזיר רשימת combos פעילים"""
        return [combo for combo in self.active_combos.values() if combo.active]
    
    def get_best_combo(self) -> Optional[DynamicCombo]:
        """מחזיר את הקומבו עם הביצועים הטובים ביותר"""
        active_combos = self.get_active_combos()
        if not active_combos:
            return None
        
        # מיון לפי profit factor
        sorted_combos = sorted(
            active_combos,
            key=lambda c: c.performance.get('profit_factor', 0),
            reverse=True
        )
        
        return sorted_combos[0] if sorted_combos else None


__all__ = ["DynamicComboGenerator", "DynamicCombo", "IndicatorConfig", "ComboType"]
