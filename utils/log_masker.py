# utils/log_masker.py
# -*- coding: utf-8 -*-
"""
בס"ד
Sensitive Data Masking for Logs
Masks API keys, secrets, and trade amounts in logs
"""
from __future__ import annotations

import re
import logging
from typing import Any, Dict, Optional

logger = logging.getLogger("algogpt.log_masker")


class LogMasker:
    """Mask sensitive data in logs"""
    
    def __init__(self):
        # Patterns for sensitive data
        self.api_key_pattern = re.compile(
            r'(api[_-]?key|apikey|secret|token|password)["\s:=]+([A-Za-z0-9_-]{20,})',
            re.IGNORECASE
        )
        self.bearer_pattern = re.compile(
            r'Bearer\s+([A-Za-z0-9_-]{20,})',
            re.IGNORECASE
        )
        # Binance-style API keys (usually 64 chars)
        self.binance_key_pattern = re.compile(
            r'[A-Za-z0-9]{64}'
        )
    
    def mask_api_key(self, key: str) -> str:
        """
        Mask API key showing only first 4 and last 4 characters
        
        Example: 
            'abcdefghijklmnopqrstuvwxyz1234567890' -> 'abcd...7890'
        """
        if not key or len(key) < 12:
            return "***"
        
        return f"{key[:4]}...{key[-4:]}"
    
    def mask_amount(self, amount: float, threshold: float = 100.0) -> str:
        """
        Mask trade amounts above threshold
        
        Args:
            amount: The amount to potentially mask
            threshold: Amounts above this are masked
            
        Returns:
            Original amount as string if below threshold, otherwise masked
        """
        if abs(amount) < threshold:
            return str(amount)
        
        # Show magnitude only (e.g., 1234.56 -> "~1200")
        magnitude = 10 ** (len(str(int(abs(amount)))) - 2)
        masked = int(abs(amount) / magnitude) * magnitude
        sign = "-" if amount < 0 else ""
        return f"{sign}~{masked}"
    
    def mask_dict(self, data: Dict[str, Any], mask_amounts: bool = True) -> Dict[str, Any]:
        """
        Recursively mask sensitive fields in a dictionary
        
        Args:
            data: Dictionary to mask
            mask_amounts: Whether to mask amount fields
            
        Returns:
            New dictionary with masked values
        """
        if not isinstance(data, dict):
            return data
        
        masked = {}
        sensitive_keys = {
            'api_key', 'apikey', 'secret', 'token', 'password', 
            'authorization', 'auth', 'private_key', 'access_token'
        }
        amount_keys = {'quantity', 'qty', 'amount', 'size', 'notional', 'value'}
        
        for key, value in data.items():
            key_lower = key.lower()
            
            # Mask sensitive keys
            if any(sk in key_lower for sk in sensitive_keys):
                if isinstance(value, str):
                    masked[key] = self.mask_api_key(value)
                else:
                    masked[key] = "***"
            # Mask amounts if enabled
            elif mask_amounts and any(ak in key_lower for ak in amount_keys):
                if isinstance(value, (int, float)):
                    masked[key] = self.mask_amount(float(value))
                else:
                    masked[key] = value
            # Recursively process nested dicts
            elif isinstance(value, dict):
                masked[key] = self.mask_dict(value, mask_amounts)
            # Recursively process lists
            elif isinstance(value, list):
                masked[key] = [
                    self.mask_dict(item, mask_amounts) if isinstance(item, dict) else item
                    for item in value
                ]
            else:
                masked[key] = value
        
        return masked
    
    def mask_string(self, text: str) -> str:
        """
        Mask sensitive data in string (for log messages)
        
        Args:
            text: String potentially containing sensitive data
            
        Returns:
            String with sensitive data masked
        """
        if not text:
            return text
        
        # Mask API keys in patterns like: api_key="xxxx" or apiKey: "xxxx"
        text = self.api_key_pattern.sub(
            lambda m: f'{m.group(1)}{m.group(0)[len(m.group(1)):len(m.group(1))+1]}{self.mask_api_key(m.group(2))}',
            text
        )
        
        # Mask Bearer tokens
        text = self.bearer_pattern.sub(
            lambda m: f'Bearer {self.mask_api_key(m.group(1))}',
            text
        )
        
        # Mask standalone Binance-style API keys (64 char alphanumeric)
        text = self.binance_key_pattern.sub(
            lambda m: self.mask_api_key(m.group(0)),
            text
        )
        
        return text


# Global masker instance
_log_masker: Optional[LogMasker] = None


def get_log_masker() -> LogMasker:
    """Get or create global log masker instance"""
    global _log_masker
    if _log_masker is None:
        _log_masker = LogMasker()
    return _log_masker


def mask_api_key(key: str) -> str:
    """Convenience function to mask an API key"""
    masker = get_log_masker()
    return masker.mask_api_key(key)


def mask_dict(data: Dict[str, Any], mask_amounts: bool = True) -> Dict[str, Any]:
    """Convenience function to mask a dictionary"""
    masker = get_log_masker()
    return masker.mask_dict(data, mask_amounts)


def mask_string(text: str) -> str:
    """Convenience function to mask a string"""
    masker = get_log_masker()
    return masker.mask_string(text)


class MaskingFormatter(logging.Formatter):
    """Logging formatter that masks sensitive data"""
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.masker = get_log_masker()
    
    def format(self, record: logging.LogRecord) -> str:
        # Mask the message
        original_msg = record.getMessage()
        record.msg = self.masker.mask_string(str(record.msg))
        
        # Format the record
        formatted = super().format(record)
        
        # Restore original (in case record is reused)
        record.msg = original_msg
        
        return formatted
