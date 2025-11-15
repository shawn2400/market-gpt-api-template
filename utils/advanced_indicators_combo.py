# utils/advanced_indicators_combo.py
"""
🎯 Advanced Indicators Combo System
5 pre-defined strategies with confidence scoring and dynamic regime detection
"""

from __future__ import annotations
import logging
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger("algogpt.indicators_combo")


class MarketRegime(Enum):
    """מצב שוק"""
    TRENDING_UP = "trending_up"
    TRENDING_DOWN = "trending_down"
    CHOPPY = "choppy"
    VOLATILE = "volatile"
    SIDEWAYS = "sideways"


class ComboStrength(Enum):
    """חוזק הקומבו"""
    STRONG = "strong"
    MODERATE = "moderate"
    WEAK = "weak"


@dataclass
class ComboSignal:
    """אות ממערכת שילוב אינדיקטורים"""
    name: str
    strength: ComboStrength
    direction: str  # "long" or "short"
    confidence: float  # 0-1
    conditions_met: List[str]
    conditions_failed: List[str]
    indicators_used: List[str]
    recommended_action: str
    regime: Optional[MarketRegime] = None


class AdvancedIndicatorsCombo:
    """
    🎯 מערכת שילובי אינדיקטורים מתקדמת
    
    5 קומבויים מוגדרים מראש:
    1. מגמה חזקה + מומנטום + תמיכה
    2. פריצה עם נפח ווליטיליות
    3. פולבק איכותי במגמה
    4. מגמת ירידה עם התנגדות
    5. שוק מתנדנד עם גבולות
    """
    
    def __init__(self):
        self.combos_registry = {}
        self._setup_combos()
    
    def _setup_combos(self):
        """מגדיר את כל שילובי האינדיקטורים"""
        self.combos_registry = {
            "strong_trend_momentum": self._calc_strong_trend_combo,
            "breakout_volume": self._calc_breakout_combo,
            "quality_pullback": self._calc_pullback_combo,
            "downtrend_resistance": self._calc_downtrend_combo,
            "ranging_market": self._calc_ranging_combo,
        }
    
    def analyze_market_regime(self, data: Dict[str, Any]) -> MarketRegime:
        """
        🔍 מנתח את סוג השוק הנוכחי
        
        Args:
            data: מידע על המשתנים הטכניים (EMA, ADX, ATR, etc.)
        
        Returns:
            MarketRegime
        """
        ema_9 = data.get('ema_9', 0)
        ema_20 = data.get('ema_20', 0)
        ema_50 = data.get('ema_50', 0)
        adx = data.get('adx', 0)
        atr_percentage = data.get('atr_percentage', 0)
        
        # ניתוח מגמה
        if adx > 25:
            if ema_9 > ema_20 > ema_50:
                return MarketRegime.TRENDING_UP
            elif ema_9 < ema_20 < ema_50:
                return MarketRegime.TRENDING_DOWN
        
        # ניתוח תנודתיות
        if atr_percentage > 0.03:  # 3% ATR
            return MarketRegime.VOLATILE
        
        # ניתוח שוק מתנדנד
        if adx < 20:
            return MarketRegime.CHOPPY
        
        return MarketRegime.SIDEWAYS
    
    def analyze_all_combos(self, data: Dict[str, Any]) -> List[ComboSignal]:
        """
        📊 מנתח את כל הקומבויים ומחזיר את המתאימים
        
        Args:
            data: נתוני שוק ואינדיקטורים
        
        Returns:
            רשימת signals ממוינת לפי confidence (הגבוה ביותר ראשון)
        """
        signals = []
        regime = self.analyze_market_regime(data)
        
        for combo_name, combo_func in self.combos_registry.items():
            try:
                signal = combo_func(data)
                signal.regime = regime
                
                # רק signals עם confidence מעל 0.5
                if signal.confidence >= 0.5:
                    signals.append(signal)
                    logger.debug(f"✅ {combo_name}: {signal.confidence:.2f} confidence")
                else:
                    logger.debug(f"⏭️ {combo_name}: {signal.confidence:.2f} confidence (too low)")
                    
            except Exception as e:
                logger.warning(f"Failed to calculate combo {combo_name}: {e}")
        
        # מיין לפי confidence
        signals.sort(key=lambda x: x.confidence, reverse=True)
        return signals
    
    def get_best_combo(self, data: Dict[str, Any]) -> Optional[ComboSignal]:
        """מחזיר את הקומבו הטוב ביותר"""
        signals = self.analyze_all_combos(data)
        return signals[0] if signals else None
    
    # ========================
    # COMBO 1: מגמה חזקה + מומנטום + תמיכה
    # ========================
    def _calc_strong_trend_combo(self, data: Dict) -> ComboSignal:
        """
        🟢 COMBO 1: מגמה חזקה + מומנטום + תמיכה
        
        תנאים:
        - EMA 9 > EMA 20 > EMA 50 (מגמה עולה)
        - ADX > 25 (מגמה חזקה)
        - RSI בין 35-65 (מומנטום מאוזן)
        - קרוב לתמיכה
        - ווליום גבוה
        """
        score = 0
        max_score = 6
        conditions_met = []
        conditions_failed = []
        
        ema_9 = data.get('ema_9', 0)
        ema_20 = data.get('ema_20', 0)
        ema_50 = data.get('ema_50', 0)
        adx = data.get('adx', 0)
        rsi = data.get('rsi', 50)
        
        # תנאי 1: מגמה חזקה (2 נקודות)
        if ema_9 > ema_20 > ema_50:
            score += 2
            conditions_met.append("✅ מגמה עולה חזקה (EMA9>EMA20>EMA50)")
            direction = "long"
        elif ema_9 < ema_20 < ema_50:
            score += 2
            conditions_met.append("✅ מגמה יורדת חזקה (EMA9<EMA20<EMA50)")
            direction = "short"
        else:
            conditions_failed.append("❌ אין מגמה ברורה")
            # FIX: Never return neutral - default to long if no clear trend
            direction = "long" if ema_9 > ema_50 else "short"
        
        # תנאי 2: ADX חזק (1 נקודה)
        if adx > 25:
            score += 1
            conditions_met.append(f"✅ מגמה חזקה (ADX={adx:.1f}>25)")
        else:
            conditions_failed.append(f"❌ מגמה חלשה (ADX={adx:.1f}<25)")
        
        # תנאי 3: RSI אופטימלי (1 נקודה)
        if 35 <= rsi <= 65:
            score += 1
            conditions_met.append(f"✅ RSI באזור אופטימלי ({rsi:.1f})")
        else:
            conditions_failed.append(f"❌ RSI לא אופטימלי ({rsi:.1f})")
        
        # תנאי 4: תמיכה/התנגדות (1 נקודה)
        if data.get('near_support') or data.get('near_resistance'):
            score += 1
            conditions_met.append("✅ קרוב לקו תמיכה/התנגדות משמעותי")
        else:
            conditions_failed.append("❌ לא קרוב לתמיכה/התנגדות")
        
        # תנאי 5: ווליום (1 נקודה)
        if data.get('volume_above_avg'):
            score += 1
            conditions_met.append("✅ ווליום גבוה מהממוצע")
        else:
            conditions_failed.append("❌ ווליום נמוך")
        
        confidence = score / max_score
        strength = (
            ComboStrength.STRONG if confidence >= 0.7
            else ComboStrength.MODERATE if confidence >= 0.5
            else ComboStrength.WEAK
        )
        
        return ComboSignal(
            name="מגמה חזקה + מומנטום + תמיכה",
            strength=strength,
            direction=direction,
            confidence=confidence,
            conditions_met=conditions_met,
            conditions_failed=conditions_failed,
            indicators_used=["EMA_9", "EMA_20", "EMA_50", "RSI", "ADX", "Support/Resistance", "Volume"],
            recommended_action=f"ENTER {direction.upper()} עם 1-2% מהון" if confidence >= 0.7 else f"ENTER {direction.upper()} עם 0.5-1% מהון"
        )
    
    # ========================
    # COMBO 2: פריצה עם נפח ווליטיליות
    # ========================
    def _calc_breakout_combo(self, data: Dict) -> ComboSignal:
        """
        🟢 COMBO 2: פריצה עם אישורי נפח ווליטיליות
        
        תנאים:
        - פריצה התרחשה
        - ווליום גבוה בפריצה (2x ממוצע)
        - ATR מתאים (>2%)
        - VWAP אישור
        - RSI לא overbought/oversold
        """
        score = 0
        max_score = 5
        conditions_met = []
        conditions_failed = []
        
        # תנאי 1: פריצה (2 נקודות)
        if data.get('breakout_occurred'):
            score += 2
            breakout_dir = data.get('breakout_direction', 'up')
            conditions_met.append(f"✅ פריצה {breakout_dir} מתרחשת/התרחשה")
            direction = "long" if breakout_dir == "up" else "short"
        else:
            conditions_failed.append("❌ אין פריצה")
            # FIX: Never return neutral - default to current price trend
            direction = "long"
        
        # תנאי 2: ווליום פריצה (1 נקודה)
        if data.get('volume_breakout'):
            score += 1
            conditions_met.append("✅ ווליום גבוה בפריצה (>2x ממוצע)")
        else:
            conditions_failed.append("❌ ווליום נמוך בפריצה")
        
        # תנאי 3: ATR מתאים (1 נקודה)
        atr_pct = data.get('atr_percentage', 0)
        if atr_pct > 0.02:  # 2%
            score += 1
            conditions_met.append(f"✅ תנודתיות מתאימה (ATR={atr_pct*100:.1f}%)")
        else:
            conditions_failed.append(f"❌ תנודתיות נמוכה (ATR={atr_pct*100:.1f}%)")
        
        # תנאי 4: VWAP אישור (1 נקודה)
        if data.get('price_above_vwap'):
            score += 1
            conditions_met.append("✅ מחיר מעל VWAP")
        else:
            conditions_failed.append("❌ מחיר מתחת VWAP")
        
        confidence = score / max_score
        strength = (
            ComboStrength.STRONG if confidence >= 0.7
            else ComboStrength.MODERATE if confidence >= 0.5
            else ComboStrength.WEAK
        )
        
        return ComboSignal(
            name="פריצה עם נפח ווליטיליות",
            strength=strength,
            direction=direction,
            confidence=confidence,
            conditions_met=conditions_met,
            conditions_failed=conditions_failed,
            indicators_used=["Breakout", "Volume", "ATR", "VWAP", "RSI"],
            recommended_action=f"ENTER {direction.upper()} עם 1-1.5% מהון" if confidence >= 0.7 else f"ENTER {direction.upper()} עם 0.5-1% מהון"
        )
    
    # ========================
    # COMBO 3: פולבק איכותי במגמה
    # ========================
    def _calc_pullback_combo(self, data: Dict) -> ComboSignal:
        """
        🟢 COMBO 3: פולבק איכותי במגמה חזקה
        
        תנאים:
        - מגמה ראשית עולה (EMA 20 > EMA 50)
        - פולבק לתמיכה משמעותית
        - RSI oversold קל במגמה עולה (<40)
        - MACD histogram משתפר
        """
        score = 0
        max_score = 6
        conditions_met = []
        conditions_failed = []
        
        ema_20 = data.get('ema_20', 0)
        ema_50 = data.get('ema_50', 0)
        rsi = data.get('rsi', 50)
        
        # תנאי 1: מגמה ראשית (2 נקודות)
        # NOTE: Pullback combo is LONG-ONLY (pullback to support in uptrend)
        if ema_20 > ema_50:
            score += 2
            conditions_met.append("✅ מגמה ראשית עולה (EMA20>EMA50)")
        else:
            conditions_failed.append("❌ אין מגמה עולה (pullback works only in uptrend)")
        
        # Always long for pullback combo
        direction = "long"
        
        # תנאי 2: פולבק לתמיכה (2 נקודות)
        if data.get('pullback_to_support'):
            score += 2
            conditions_met.append("✅ פולבק לתמיכה משמעותית")
        else:
            conditions_failed.append("❌ לא בפולבק לתמיכה")
        
        # תנאי 3: RSI oversold במגמה עולה (1 נקודה)
        if rsi < 40 and ema_20 > ema_50:
            score += 1
            conditions_met.append(f"✅ RSI oversold קל ({rsi:.1f}<40)")
        else:
            conditions_failed.append(f"❌ RSI לא oversold ({rsi:.1f})")
        
        # תנאי 4: MACD אישור (1 נקודה)
        if data.get('macd_histogram_turning'):
            score += 1
            conditions_met.append("✅ MACD histogram משתפר")
        else:
            conditions_failed.append("❌ MACD histogram לא משתפר")
        
        confidence = score / max_score
        strength = (
            ComboStrength.STRONG if confidence >= 0.75
            else ComboStrength.MODERATE if confidence >= 0.5
            else ComboStrength.WEAK
        )
        
        return ComboSignal(
            name="פולבק איכותי במגמה",
            strength=strength,
            direction=direction,
            confidence=confidence,
            conditions_met=conditions_met,
            conditions_failed=conditions_failed,
            indicators_used=["EMA_20", "EMA_50", "RSI", "MACD", "Support", "VWAP"],
            recommended_action="ENTER LONG עם 1-2% מהון - פוטנציאל גבוה" if confidence >= 0.75 else "ENTER LONG עם 0.5-1% מהון"
        )
    
    # ========================
    # COMBO 4: מגמת ירידה עם התנגדות
    # ========================
    def _calc_downtrend_combo(self, data: Dict) -> ComboSignal:
        """
        🔴 COMBO 4: מגמת ירידה עם אישורי התנגדות ומומנטום
        
        תנאים:
        - מגמה יורדת (EMA 20 < EMA 50)
        - קרוב להתנגדות
        - RSI overbought במגמת ירידה (>60)
        - ווליום תומך
        """
        score = 0
        max_score = 5
        conditions_met = []
        conditions_failed = []
        
        ema_20 = data.get('ema_20', 0)
        ema_50 = data.get('ema_50', 0)
        rsi = data.get('rsi', 50)
        
        # תנאי 1: מגמת ירידה (2 נקודות)
        if ema_20 < ema_50:
            score += 2
            conditions_met.append("✅ מגמה ראשית יורדת (EMA20<EMA50)")
            direction = "short"
        elif ema_20 > ema_50:
            score += 1
            conditions_met.append("✅ מגמה ראשית עולה (EMA20>EMA50)")
            direction = "long"
        else:
            conditions_failed.append("❌ אין מגמה ברורה")
            # FIX: Never return neutral - default to short for downtrend combo
            direction = "short"
        
        # תנאי 2: התנגדות (1 נקודה)
        if data.get('near_resistance'):
            score += 1
            conditions_met.append("✅ קרוב להתנגדות משמעותית")
        else:
            conditions_failed.append("❌ לא קרוב להתנגדות")
        
        # תנאי 3: RSI overbought במגמת ירידה (1 נקודה)
        if rsi > 60 and ema_20 < ema_50:
            score += 1
            conditions_met.append(f"✅ RSI overbought קל ({rsi:.1f}>60)")
        else:
            conditions_failed.append(f"❌ RSI לא overbought ({rsi:.1f})")
        
        # תנאי 4: ווליום אישור (1 נקודה)
        if data.get('volume_above_avg'):
            score += 1
            conditions_met.append("✅ ווליום תומך")
        else:
            conditions_failed.append("❌ ווליום נמוך")
        
        confidence = score / max_score
        strength = (
            ComboStrength.STRONG if confidence >= 0.7
            else ComboStrength.MODERATE if confidence >= 0.5
            else ComboStrength.WEAK
        )
        
        return ComboSignal(
            name="מגמת ירידה עם התנגדות",
            strength=strength,
            direction=direction,
            confidence=confidence,
            conditions_met=conditions_met,
            conditions_failed=conditions_failed,
            indicators_used=["EMA_20", "EMA_50", "RSI", "ADX", "Resistance", "Volume"],
            recommended_action="ENTER SHORT עם 1-1.5% מהון" if confidence >= 0.7 else "ENTER SHORT עם 0.5-1% מהון"
        )
    
    # ========================
    # COMBO 5: שוק מתנדנד עם גבולות
    # ========================
    def _calc_ranging_combo(self, data: Dict) -> ComboSignal:
        """
        🟡 COMBO 5: שוק מתנדנד עם גבולות ברורים
        
        תנאים:
        - Bollinger Bands צרים/שטוחים
        - RSI באזור קיצוני (<35 או >65)
        - גבולות תמיכה/התנגדות ברורים
        - ווליום נמוך
        """
        score = 0
        max_score = 5
        conditions_met = []
        conditions_failed = []
        
        rsi = data.get('rsi', 50)
        bb_width = data.get('bb_width', 0)
        
        # תנאי 1: Bollinger Bands flat (2 נקודות)
        if data.get('bb_squeeze') or bb_width < 0.03:
            score += 2
            conditions_met.append("✅ Bollinger Bands צרים/שטוחים")
        else:
            conditions_failed.append("❌ Bollinger Bands רחבים")
        
        # תנאי 2: RSI באזור edges (1 נקודה)
        if rsi < 35:
            score += 1
            conditions_met.append(f"✅ RSI oversold ({rsi:.1f}<35) - long opportunity")
            direction = "long"
        elif rsi > 65:
            score += 1
            conditions_met.append(f"✅ RSI overbought ({rsi:.1f}>65) - short opportunity")
            direction = "short"
        else:
            conditions_failed.append(f"❌ RSI באמצע ({rsi:.1f})")
            # FIX: Never return neutral - use RSI threshold to decide
            direction = "long" if rsi < 50 else "short"
        
        # תנאי 3: תמיכה/התנגדות ברורים (1 נקודה)
        if data.get('clear_support_resistance'):
            score += 1
            conditions_met.append("✅ גבולות תמיכה/התנגדות ברורים")
        else:
            conditions_failed.append("❌ אין גבולות ברורים")
        
        # תנאי 4: ווליום נמוך (1 נקודה)
        if data.get('volume_below_avg'):
            score += 1
            conditions_met.append("✅ ווליום נמוך - שוק מתנדנד")
        else:
            conditions_failed.append("❌ ווליום גבוה")
        
        confidence = score / max_score
        strength = (
            ComboStrength.STRONG if confidence >= 0.7
            else ComboStrength.MODERATE if confidence >= 0.6
            else ComboStrength.WEAK
        )
        
        return ComboSignal(
            name="שוק מתנדנד עם גבולות",
            strength=strength,
            direction=direction,
            confidence=confidence,
            conditions_met=conditions_met,
            conditions_failed=conditions_failed,
            indicators_used=["Bollinger_Bands", "RSI", "Support", "Resistance", "Volume"],
            recommended_action=f"ENTER {direction.upper()} עם 0.5-1% מהון (range trading)" if confidence >= 0.6 else "WAIT - אין setup ברור"
        )


__all__ = ["AdvancedIndicatorsCombo", "ComboSignal", "MarketRegime", "ComboStrength"]
