# utils/rate_limiter.py
# -*- coding: utf-8 -*-
"""
בס"ד
Rate Limiting System with in-memory counters
Tracks requests per endpoint with configurable time windows
"""
from __future__ import annotations

import time
import logging
from typing import Dict, Tuple, Optional
from collections import defaultdict
from threading import Lock

logger = logging.getLogger("algogpt.rate_limiter")


class RateLimiter:
    """In-memory rate limiter with time windows"""
    
    def __init__(self):
        # endpoint -> (max_requests, window_seconds)
        self.limits: Dict[str, Tuple[int, int]] = {
            "/validate/run": (10, 60),  # 10 requests per minute
            "/monitors/health": (60, 60),  # 60 requests per minute
            "/api/health": (100, 60),  # 100 requests per minute
            "/health": (100, 60),
            "/readyz": (100, 60),
            "/dashboard/ultimate-data": (30, 60),  # 30 requests per minute
            "/context/batch": (20, 60),  # 20 requests per minute
        }
        
        # (endpoint, client_id) -> [(timestamp1, timestamp2, ...)]
        self.requests: Dict[Tuple[str, str], list] = defaultdict(list)
        self.lock = Lock()
    
    def configure_limit(self, endpoint: str, max_requests: int, window_seconds: int):
        """
        Configure rate limit for an endpoint
        
        Args:
            endpoint: Endpoint path
            max_requests: Maximum requests allowed
            window_seconds: Time window in seconds
        """
        with self.lock:
            self.limits[endpoint] = (max_requests, window_seconds)
            logger.info(f"Rate limit configured: {endpoint} -> {max_requests} req/{window_seconds}s")
    
    def check_rate_limit(self, endpoint: str, client_id: str = "default") -> Tuple[bool, Optional[int]]:
        """
        Check if request is within rate limit
        
        Args:
            endpoint: Endpoint path
            client_id: Client identifier (IP, user_id, etc.)
            
        Returns:
            Tuple of (allowed: bool, retry_after: Optional[int])
            If not allowed, retry_after indicates seconds to wait
        """
        # Get limit config for this endpoint
        limit_config = self.limits.get(endpoint)
        if not limit_config:
            # No limit configured, allow by default
            return (True, None)
        
        max_requests, window_seconds = limit_config
        now = time.time()
        key = (endpoint, client_id)
        
        with self.lock:
            # Get request history for this endpoint+client
            request_times = self.requests[key]
            
            # Remove requests outside the time window
            cutoff = now - window_seconds
            request_times[:] = [t for t in request_times if t > cutoff]
            
            # Check if limit exceeded
            if len(request_times) >= max_requests:
                # Calculate retry_after (time until oldest request expires)
                oldest = request_times[0] if request_times else now
                retry_after = int(oldest + window_seconds - now) + 1
                logger.warning(
                    f"Rate limit exceeded: {endpoint} for {client_id} "
                    f"({len(request_times)}/{max_requests} in {window_seconds}s)"
                )
                return (False, retry_after)
            
            # Add current request
            request_times.append(now)
            return (True, None)
    
    def reset_client(self, client_id: str):
        """Reset rate limit counters for a specific client"""
        with self.lock:
            keys_to_delete = [k for k in self.requests.keys() if k[1] == client_id]
            for key in keys_to_delete:
                del self.requests[key]
            logger.info(f"Rate limit reset for client: {client_id}")
    
    def reset_endpoint(self, endpoint: str):
        """Reset rate limit counters for a specific endpoint"""
        with self.lock:
            keys_to_delete = [k for k in self.requests.keys() if k[0] == endpoint]
            for key in keys_to_delete:
                del self.requests[key]
            logger.info(f"Rate limit reset for endpoint: {endpoint}")
    
    def get_stats(self) -> Dict[str, Any]:
        """Get current rate limiting statistics"""
        with self.lock:
            stats = {
                "total_tracked_keys": len(self.requests),
                "limits": {
                    endpoint: {"max_requests": max_req, "window_seconds": window}
                    for endpoint, (max_req, window) in self.limits.items()
                },
                "active_clients": len(set(k[1] for k in self.requests.keys())),
            }
            return stats


# Global rate limiter instance
_rate_limiter: Optional[RateLimiter] = None


def get_rate_limiter() -> RateLimiter:
    """Get or create global rate limiter instance"""
    global _rate_limiter
    if _rate_limiter is None:
        _rate_limiter = RateLimiter()
    return _rate_limiter
