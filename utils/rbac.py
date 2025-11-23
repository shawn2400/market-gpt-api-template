#!/usr/bin/env python3
# utils/rbac.py
"""
Role-Based Access Control (RBAC) Middleware
============================================
Enforces ADMIN/USER/VIEWER permissions
"""

from __future__ import annotations
from typing import Optional, List
from functools import wraps
from fastapi import HTTPException, Depends, Request
from sqlalchemy.orm import Session

from utils.user_models import User, get_db, SessionLocal
import logging

logger = logging.getLogger("algogpt.rbac")


class RoleChecker:
    """Check user roles and permissions"""
    
    @staticmethod
    def get_user_from_token(token: Optional[str]) -> Optional[User]:
        """Get user from API token or Telegram token"""
        if not token:
            return None
        
        db = SessionLocal()
        try:
            # Check by API key
            user = db.query(User).filter(User.api_key == token).first()
            if user:
                return user
            
            # Check by one-tap token
            user = db.query(User).filter(User.one_tap_token == token).first()
            if user and user.one_tap_expires_at:
                from datetime import datetime
                if user.one_tap_expires_at > datetime.utcnow():
                    return user
            
            return None
        finally:
            db.close()
    
    @staticmethod
    def require_role(required_role: str):
        """Decorator to require specific role"""
        def decorator(func):
            @wraps(func)
            async def wrapper(request: Request, *args, **kwargs):
                # Get token from header
                auth_header = request.headers.get("Authorization", "")
                token = auth_header.replace("Bearer ", "").strip() if auth_header else None
                
                if not token:
                    raise HTTPException(status_code=401, detail="No token provided")
                
                user = RoleChecker.get_user_from_token(token)
                if not user:
                    raise HTTPException(status_code=401, detail="Invalid token")
                
                if not user.is_active:
                    raise HTTPException(status_code=403, detail="User account disabled")
                
                # Check role hierarchy
                role_hierarchy = {
                    "admin": 3,
                    "user": 2,
                    "viewer": 1
                }
                
                user_level = role_hierarchy.get(user.role, 0)
                required_level = role_hierarchy.get(required_role, 0)
                
                if user_level < required_level:
                    raise HTTPException(
                        status_code=403,
                        detail=f"Insufficient permissions. Required: {required_role}, Got: {user.role}"
                    )
                
                # Inject user into request state
                request.state.user = user
                
                return await func(request, *args, **kwargs) if hasattr(func, "__await__") else func(request, *args, **kwargs)
            
            return wrapper
        return decorator


def require_admin(request: Request):
    """Dependency: require admin role"""
    auth_header = request.headers.get("Authorization", "")
    token = auth_header.replace("Bearer ", "").strip() if auth_header else None
    
    if not token:
        raise HTTPException(status_code=401, detail="No token provided")
    
    user = RoleChecker.get_user_from_token(token)
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="Invalid token")
    
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin role required")
    
    return user


def require_user(request: Request):
    """Dependency: require user or admin role"""
    auth_header = request.headers.get("Authorization", "")
    token = auth_header.replace("Bearer ", "").strip() if auth_header else None
    
    if not token:
        raise HTTPException(status_code=401, detail="No token provided")
    
    user = RoleChecker.get_user_from_token(token)
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="Invalid token")
    
    if user.role not in ["admin", "user"]:
        raise HTTPException(status_code=403, detail="User role required")
    
    return user


def require_viewer(request: Request):
    """Dependency: require viewer/user/admin role"""
    auth_header = request.headers.get("Authorization", "")
    token = auth_header.replace("Bearer ", "").strip() if auth_header else None
    
    if not token:
        raise HTTPException(status_code=401, detail="No token provided")
    
    user = RoleChecker.get_user_from_token(token)
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="Invalid token")
    
    return user
