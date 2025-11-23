#!/usr/bin/env python3
# utils/user_models.py
"""
User Database Models + Authentication
=====================================
SQLAlchemy models for Multi-User system with RBAC
"""

from __future__ import annotations
from datetime import datetime
from typing import Optional, Dict, Any
import uuid
import logging

logger = logging.getLogger("algogpt.user_models")

# ============================================================================
# Pydantic Models (for API)
# ============================================================================

from pydantic import BaseModel, EmailStr, Field


class RoleEnum:
    ADMIN = "admin"
    USER = "user"
    VIEWER = "viewer"


class UserCreate(BaseModel):
    telegram_id: str
    username: str
    email: Optional[str] = None
    role: str = "user"


class UserUpdate(BaseModel):
    username: Optional[str] = None
    email: Optional[str] = None
    role: Optional[str] = None
    is_active: Optional[bool] = None


class UserResponse(BaseModel):
    id: str
    telegram_id: str
    username: str
    email: Optional[str] = None
    role: str
    is_active: bool
    created_at: datetime
    last_login_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class TelegramAuthRequest(BaseModel):
    telegram_id: str
    username: str
    first_name: str
    last_name: Optional[str] = None
    photo_url: Optional[str] = None


class TelegramQRCode(BaseModel):
    qr_code_data: str
    one_tap_url: str
    expires_at: datetime


# ============================================================================
# SQLAlchemy Models (for Database)
# ============================================================================

from sqlalchemy import create_engine, Column, String, Boolean, DateTime, Integer, Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import os

DATABASE_URL = os.getenv("DATABASE_URL", "")
if not DATABASE_URL:
    raise ValueError("DATABASE_URL environment variable not set")

engine = create_engine(DATABASE_URL, echo=False)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class User(Base):
    """User account model"""
    __tablename__ = "users"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    telegram_id = Column(String(100), unique=True, nullable=False, index=True)
    username = Column(String(255), unique=True, nullable=False, index=True)
    email = Column(String(255), unique=True, nullable=True)
    
    # Role-based access control
    role = Column(String(20), default=RoleEnum.USER, nullable=False)  # admin, user, viewer
    
    # Account status
    is_active = Column(Boolean, default=True, nullable=False)
    
    # API key for programmatic access
    api_key = Column(String(64), unique=True, nullable=True, index=True)
    
    # Metadata
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    last_login_at = Column(DateTime, nullable=True)
    last_ip = Column(String(45), nullable=True)  # IPv4 or IPv6
    
    # Profile
    first_name = Column(String(255), nullable=True)
    last_name = Column(String(255), nullable=True)
    photo_url = Column(Text, nullable=True)
    
    # Telegram one-tap session
    one_tap_token = Column(String(128), unique=True, nullable=True, index=True)
    one_tap_expires_at = Column(DateTime, nullable=True)
    
    # QR code tracking
    qr_code_token = Column(String(128), unique=True, nullable=True, index=True)
    qr_code_generated_at = Column(DateTime, nullable=True)
    
    # Wallet address for profit-share payouts
    wallet_address = Column(String(255), nullable=True)
    
    def has_role(self, role: str) -> bool:
        """Check if user has specific role"""
        if self.role == RoleEnum.ADMIN:
            return True  # Admin has all permissions
        return self.role == role
    
    def has_permission(self, action: str) -> bool:
        """Check if user can perform action based on role"""
        permissions = {
            RoleEnum.ADMIN: ["read", "write", "execute", "admin"],
            RoleEnum.USER: ["read", "write", "execute"],
            RoleEnum.VIEWER: ["read"]
        }
        return action in permissions.get(self.role, [])
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dict"""
        return {
            "id": self.id,
            "telegram_id": self.telegram_id,
            "username": self.username,
            "email": self.email,
            "role": self.role,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat(),
            "last_login_at": self.last_login_at.isoformat() if self.last_login_at else None,
        }


class UserSession(Base):
    """User session tracking"""
    __tablename__ = "user_sessions"
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String(36), nullable=False, index=True)
    token = Column(String(256), unique=True, nullable=False, index=True)
    ip_address = Column(String(45), nullable=True)
    user_agent = Column(Text, nullable=True)
    
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    expires_at = Column(DateTime, nullable=False)
    last_activity_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    
    is_active = Column(Boolean, default=True, nullable=False)


def init_database():
    """Initialize database tables"""
    try:
        Base.metadata.create_all(bind=engine)
        logger.info("✅ Database tables initialized successfully")
        return True
    except Exception as e:
        logger.error(f"❌ Failed to initialize database: {e}")
        return False


def get_db():
    """Get database session"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
