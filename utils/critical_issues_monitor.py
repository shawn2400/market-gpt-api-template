#!/usr/bin/env python3
"""
Critical Issues Monitor - MetaBrain v9.2.5
=========================================================================
Real-time monitoring of critical system points with alert thresholds.

Tracks:
- Precision errors
- Order execution failures  
- Position management issues
- Adaptive system performance
- Risk management metrics

Sends alerts when thresholds are exceeded.
"""

import logging
from datetime import datetime
from typing import Dict, Any, List
from utils.redis_client import get_redis

logger = logging.getLogger("critical_issues_monitor")


class CriticalIssuesMonitor:
    """
    Real-time monitoring of critical system metrics.
    """
    
    def __init__(self):
        self.logger = logger
        self.redis = get_redis()
        
        # Define alert thresholds
        self.alert_thresholds = {
            'win_rate_below': 0.45,
            'error_rate_above': 0.05,
            'position_failures_above': 2,
            'api_errors_above': 10,
            'margin_ratio_below': 0.10,
            'order_rejection_above': 5,
            'tp_sl_failure_above': 3,
            'precision_errors_above': 2
        }
    
    async def check_all_metrics(self) -> Dict[str, Any]:
        """
        Check all critical metrics and return alert status.
        """
        alerts = []
        metrics = {}
        
        self.logger.info("📊 Checking critical metrics...")
        
        # Check each metric
        checks = [
            ('win_rate', self._check_win_rate),
            ('error_rate', self._check_error_rate),
            ('position_failures', self._check_position_failures),
            ('api_errors', self._check_api_errors),
            ('margin_ratio', self._check_margin_ratio),
            ('order_rejections', self._check_order_rejections),
            ('tp_sl_failures', self._check_tp_sl_failures),
            ('precision_errors', self._check_precision_errors),
        ]
        
        for metric_name, check_func in checks:
            try:
                result = check_func()
                metrics[metric_name] = result
                
                if result.get('alert'):
                    alerts.append(result)
            except Exception as e:
                self.logger.error(f"Error checking {metric_name}: {e}")
        
        return {
            'timestamp': datetime.now().isoformat(),
            'metric_count': len(metrics),
            'alert_count': len(alerts),
            'alerts': alerts,
            'metrics': metrics,
            'critical': len([a for a in alerts if a.get('severity') == 'CRITICAL']) > 0
        }
    
    def _check_win_rate(self) -> Dict[str, Any]:
        """Monitor win rate"""
        if not self.redis:
            return {'metric': 'win_rate', 'value': None, 'alert': False}
        
        try:
            win_rate = float(self.redis.get("performance:win_rate") or 0.5)
            threshold = self.alert_thresholds['win_rate_below']
            
            result = {
                'metric': 'win_rate',
                'value': win_rate,
                'threshold': threshold,
                'alert': win_rate < threshold,
                'severity': 'HIGH' if win_rate < threshold else 'OK'
            }
            
            if result['alert']:
                self.logger.warning(
                    f"⚠️ ALERT: Win rate {win_rate:.1%} < {threshold:.1%}"
                )
                result['message'] = f"Win rate degraded to {win_rate:.1%}"
            
            return result
        except Exception as e:
            self.logger.error(f"Error checking win_rate: {e}")
            return {'metric': 'win_rate', 'error': str(e), 'alert': False}
    
    def _check_error_rate(self) -> Dict[str, Any]:
        """Monitor error rate"""
        if not self.redis:
            return {'metric': 'error_rate', 'value': None, 'alert': False}
        
        try:
            total_orders = int(self.redis.get("metrics:total_orders") or 1)
            failed_orders = int(self.redis.get("metrics:failed_orders") or 0)
            error_rate = failed_orders / total_orders if total_orders > 0 else 0
            threshold = self.alert_thresholds['error_rate_above']
            
            result = {
                'metric': 'error_rate',
                'value': error_rate,
                'threshold': threshold,
                'alert': error_rate > threshold,
                'severity': 'HIGH' if error_rate > threshold else 'OK'
            }
            
            if result['alert']:
                self.logger.warning(
                    f"⚠️ ALERT: Error rate {error_rate:.1%} > {threshold:.1%}"
                )
                result['message'] = f"Error rate high: {failed_orders}/{total_orders}"
            
            return result
        except Exception as e:
            self.logger.error(f"Error checking error_rate: {e}")
            return {'metric': 'error_rate', 'error': str(e), 'alert': False}
    
    def _check_position_failures(self) -> Dict[str, Any]:
        """Monitor position management failures"""
        if not self.redis:
            return {'metric': 'position_failures', 'value': None, 'alert': False}
        
        try:
            failures = int(self.redis.get("metrics:position_failures") or 0)
            threshold = self.alert_thresholds['position_failures_above']
            
            result = {
                'metric': 'position_failures',
                'value': failures,
                'threshold': threshold,
                'alert': failures > threshold,
                'severity': 'CRITICAL' if failures > threshold else 'OK'
            }
            
            if result['alert']:
                self.logger.critical(
                    f"🚨 CRITICAL: Position failures {failures} > {threshold}"
                )
                result['message'] = f"Critical: {failures} position failures detected"
            
            return result
        except Exception as e:
            self.logger.error(f"Error checking position_failures: {e}")
            return {'metric': 'position_failures', 'error': str(e), 'alert': False}
    
    def _check_api_errors(self) -> Dict[str, Any]:
        """Monitor API error count"""
        if not self.redis:
            return {'metric': 'api_errors', 'value': None, 'alert': False}
        
        try:
            api_errors = int(self.redis.get("metrics:api_errors_24h") or 0)
            threshold = self.alert_thresholds['api_errors_above']
            
            result = {
                'metric': 'api_errors',
                'value': api_errors,
                'threshold': threshold,
                'alert': api_errors > threshold,
                'severity': 'HIGH' if api_errors > threshold else 'OK'
            }
            
            if result['alert']:
                self.logger.warning(
                    f"⚠️ ALERT: API errors {api_errors} > {threshold}"
                )
                result['message'] = f"High API error rate: {api_errors} errors"
            
            return result
        except Exception as e:
            self.logger.error(f"Error checking api_errors: {e}")
            return {'metric': 'api_errors', 'error': str(e), 'alert': False}
    
    def _check_margin_ratio(self) -> Dict[str, Any]:
        """Monitor margin ratio for liquidation risk"""
        if not self.redis:
            return {'metric': 'margin_ratio', 'value': None, 'alert': False}
        
        try:
            margin_ratio = float(self.redis.get("account:margin_ratio") or 0.3)
            threshold = self.alert_thresholds['margin_ratio_below']
            
            result = {
                'metric': 'margin_ratio',
                'value': margin_ratio,
                'threshold': threshold,
                'alert': margin_ratio < threshold,
                'severity': 'CRITICAL' if margin_ratio < threshold else 'OK'
            }
            
            if result['alert']:
                self.logger.critical(
                    f"🚨 CRITICAL: Margin ratio {margin_ratio:.1%} < {threshold:.1%}"
                )
                result['message'] = f"CRITICAL: Liquidation risk! Margin: {margin_ratio:.1%}"
            
            return result
        except Exception as e:
            self.logger.error(f"Error checking margin_ratio: {e}")
            return {'metric': 'margin_ratio', 'error': str(e), 'alert': False}
    
    def _check_order_rejections(self) -> Dict[str, Any]:
        """Monitor order rejection count"""
        if not self.redis:
            return {'metric': 'order_rejections', 'value': None, 'alert': False}
        
        try:
            rejections = int(self.redis.get("metrics:order_rejections_24h") or 0)
            threshold = self.alert_thresholds['order_rejection_above']
            
            result = {
                'metric': 'order_rejections',
                'value': rejections,
                'threshold': threshold,
                'alert': rejections > threshold,
                'severity': 'HIGH' if rejections > threshold else 'OK'
            }
            
            if result['alert']:
                self.logger.warning(
                    f"⚠️ ALERT: Order rejections {rejections} > {threshold}"
                )
                result['message'] = f"High rejection rate: {rejections} orders rejected"
            
            return result
        except Exception as e:
            self.logger.error(f"Error checking order_rejections: {e}")
            return {'metric': 'order_rejections', 'error': str(e), 'alert': False}
    
    def _check_tp_sl_failures(self) -> Dict[str, Any]:
        """Monitor TP/SL placement failures"""
        if not self.redis:
            return {'metric': 'tp_sl_failures', 'value': None, 'alert': False}
        
        try:
            failures = len(self.redis.lrange("tp_sl_failures", 0, -1) or [])
            threshold = self.alert_thresholds['tp_sl_failure_above']
            
            result = {
                'metric': 'tp_sl_failures',
                'value': failures,
                'threshold': threshold,
                'alert': failures > threshold,
                'severity': 'CRITICAL' if failures > threshold else 'OK'
            }
            
            if result['alert']:
                self.logger.critical(
                    f"🚨 CRITICAL: TP/SL failures {failures} > {threshold}"
                )
                result['message'] = f"CRITICAL: {failures} TP/SL placement failures"
            
            return result
        except Exception as e:
            self.logger.error(f"Error checking tp_sl_failures: {e}")
            return {'metric': 'tp_sl_failures', 'error': str(e), 'alert': False}
    
    def _check_precision_errors(self) -> Dict[str, Any]:
        """Monitor precision/rounding errors"""
        if not self.redis:
            return {'metric': 'precision_errors', 'value': None, 'alert': False}
        
        try:
            errors = len(self.redis.lrange("precision_errors", 0, -1) or [])
            threshold = self.alert_thresholds['precision_errors_above']
            
            result = {
                'metric': 'precision_errors',
                'value': errors,
                'threshold': threshold,
                'alert': errors > threshold,
                'severity': 'HIGH' if errors > threshold else 'OK'
            }
            
            if result['alert']:
                self.logger.warning(
                    f"⚠️ ALERT: Precision errors {errors} > {threshold}"
                )
                result['message'] = f"Precision issues detected: {errors} errors"
            
            return result
        except Exception as e:
            self.logger.error(f"Error checking precision_errors: {e}")
            return {'metric': 'precision_errors', 'error': str(e), 'alert': False}


# Singleton instance
_monitor = None


def get_critical_issues_monitor() -> CriticalIssuesMonitor:
    """Get or create singleton monitor."""
    global _monitor
    if _monitor is None:
        _monitor = CriticalIssuesMonitor()
    return _monitor


async def check_critical_metrics() -> Dict[str, Any]:
    """Check all critical metrics."""
    monitor = get_critical_issues_monitor()
    return await monitor.check_all_metrics()
