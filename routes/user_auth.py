#!/usr/bin/env python3
# routes/user_auth.py
"""
User Authentication Routes - Multi-User System
==============================================
Features:
- Telegram QR code login
- One-Tap authentication
- Auto-Switch user
- RBAC enforcement
"""

from __future__ import annotations
from fastapi import APIRouter, Request, HTTPException, Depends, Query
from fastapi.responses import JSONResponse
from datetime import datetime, timedelta
import secrets
import logging
import os
import io
import base64
try:
    import qrcode
    QRCODE_AVAILABLE = True
except ImportError:
    QRCODE_AVAILABLE = False
from typing import Optional
from sqlalchemy.orm import Session

from utils.user_models import (
    User, UserSession, UserCreate, UserResponse, TelegramAuthRequest,
    TelegramQRCode, RoleEnum, SessionLocal, get_db
)
from utils.rbac import RoleChecker, require_admin, require_user, require_viewer

logger = logging.getLogger("algogpt.user_auth")
router = APIRouter(prefix="/auth", tags=["auth"])

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
PUBLIC_HOST = os.getenv("PUBLIC_HOST", "").rstrip("/")


# ============================================================================
# Registration & User Management
# ============================================================================

@router.post("/register", response_model=UserResponse)
async def register_user(req: TelegramAuthRequest, db: Session = Depends(get_db)):
    """
    Register new user with Telegram ID
    
    Hebrew: רישום משתמש חדש עם Telegram ID
    """
    # Check if already exists
    existing = db.query(User).filter(User.telegram_id == req.telegram_id).first()
    if existing:
        raise HTTPException(status_code=409, detail="User already exists")
    
    # Create new user
    new_user = User(
        telegram_id=req.telegram_id,
        username=req.username,
        first_name=req.first_name,
        last_name=req.last_name,
        photo_url=req.photo_url,
        role=RoleEnum.USER,  # Default role
        is_active=True
    )
    
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    
    logger.info(f"✅ User registered: {req.username} (Telegram ID: {req.telegram_id})")
    
    return UserResponse.from_orm(new_user)


# ============================================================================
# QR Code Login
# ============================================================================

def generate_qr_code(token: str) -> str:
    """Generate QR code as base64 data URL"""
    if not QRCODE_AVAILABLE:
        # Fallback: return token as simple string QR representation
        return f"QR-{token[:16]}"
    
    try:
        qr = qrcode.QRCode(version=1, box_size=10, border=5)
        qr.add_data(token)
        qr.make(fit=True)
        
        img = qr.make_image(fill_color="black", back_color="white")
        
        # Convert to base64
        buffer = io.BytesIO()
        img.save(buffer, format="PNG")
        buffer.seek(0)
        img_base64 = base64.b64encode(buffer.getvalue()).decode()
        
        return f"data:image/png;base64,{img_base64}"
    except Exception as e:
        logger.warning(f"QR generation failed: {e}, falling back to token")
        return f"QR-{token[:16]}"


@router.post("/qr/generate")
async def generate_qr_login(telegram_id: str, db: Session = Depends(get_db)):
    """
    Generate QR code for user login
    
    Hebrew: יצור קוד QR להתחברות
    """
    # Get or create user
    user = db.query(User).filter(User.telegram_id == telegram_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # Generate token
    qr_token = secrets.token_urlsafe(32)
    user.qr_code_token = qr_token
    user.qr_code_generated_at = datetime.utcnow()
    
    db.commit()
    
    # Generate QR code
    qr_data = f"{PUBLIC_HOST}/auth/qr/verify?token={qr_token}"
    qr_image = generate_qr_code(qr_data)
    
    return TelegramQRCode(
        qr_code_data=qr_image,
        one_tap_url=f"{PUBLIC_HOST}/auth/qr/verify?token={qr_token}",
        expires_at=datetime.utcnow() + timedelta(minutes=5)
    )


@router.post("/qr/verify")
async def verify_qr_token(token: str = Query(...), db: Session = Depends(get_db)):
    """
    Verify QR code token and return session token
    
    Hebrew: אימות קוד QR והחזר טוקן הפעלה
    """
    user = db.query(User).filter(User.qr_code_token == token).first()
    
    if not user:
        raise HTTPException(status_code=401, detail="Invalid QR token")
    
    # Check expiration (5 minutes)
    if user.qr_code_generated_at:
        if datetime.utcnow() - user.qr_code_generated_at > timedelta(minutes=5):
            raise HTTPException(status_code=401, detail="QR code expired")
    
    # Create session
    session_token = secrets.token_urlsafe(48)
    session = UserSession(
        user_id=user.id,
        token=session_token,
        expires_at=datetime.utcnow() + timedelta(days=7)
    )
    
    # Clear QR token
    user.qr_code_token = None
    user.last_login_at = datetime.utcnow()
    
    db.add(session)
    db.commit()
    
    logger.info(f"✅ User logged in via QR: {user.username}")
    
    return {
        "access_token": session_token,
        "token_type": "bearer",
        "user": UserResponse.from_orm(user)
    }


# ============================================================================
# One-Tap Authentication (Telegram)
# ============================================================================

@router.post("/one-tap/create")
async def create_one_tap_token(telegram_id: str, db: Session = Depends(get_db)):
    """
    Create one-tap authentication token
    
    Hebrew: יצור טוקן התחברות חד-לחיצה
    """
    user = db.query(User).filter(User.telegram_id == telegram_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # Generate token
    one_tap_token = secrets.token_urlsafe(32)
    user.one_tap_token = one_tap_token
    user.one_tap_expires_at = datetime.utcnow() + timedelta(hours=24)
    
    db.commit()
    
    return {
        "one_tap_url": f"{PUBLIC_HOST}/auth/one-tap/verify?token={one_tap_token}",
        "expires_at": user.one_tap_expires_at.isoformat()
    }


@router.post("/one-tap/verify")
async def verify_one_tap(token: str = Query(...), db: Session = Depends(get_db)):
    """
    Verify one-tap token and return session
    
    Hebrew: אימות טוקן חד-לחיצה
    """
    user = db.query(User).filter(User.one_tap_token == token).first()
    
    if not user:
        raise HTTPException(status_code=401, detail="Invalid one-tap token")
    
    # Check expiration
    if user.one_tap_expires_at and datetime.utcnow() > user.one_tap_expires_at:
        raise HTTPException(status_code=401, detail="One-tap token expired")
    
    # Create session
    session_token = secrets.token_urlsafe(48)
    session = UserSession(
        user_id=user.id,
        token=session_token,
        expires_at=datetime.utcnow() + timedelta(days=7)
    )
    
    # Clear one-tap token
    user.one_tap_token = None
    user.last_login_at = datetime.utcnow()
    
    db.add(session)
    db.commit()
    
    logger.info(f"✅ User logged in via One-Tap: {user.username}")
    
    return {
        "access_token": session_token,
        "token_type": "bearer",
        "user": UserResponse.from_orm(user)
    }


# ============================================================================
# Auto-Switch User (Admin Only)
# ============================================================================

@router.post("/switch/{user_id}")
async def admin_switch_user(user_id: str, admin_user: User = Depends(require_admin), db: Session = Depends(get_db)):
    """
    Admin switches to another user account (auto-switch)
    
    Hebrew: מנהל מחליף לחשבון משתמש אחר
    """
    target_user = db.query(User).filter(User.id == user_id).first()
    if not target_user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # Create session for target user
    session_token = secrets.token_urlsafe(48)
    session = UserSession(
        user_id=target_user.id,
        token=session_token,
        expires_at=datetime.utcnow() + timedelta(hours=1)  # Short-lived
    )
    
    target_user.last_login_at = datetime.utcnow()
    
    db.add(session)
    db.commit()
    
    logger.info(f"⚠️ Admin {admin_user.username} switched to user {target_user.username}")
    
    return {
        "access_token": session_token,
        "token_type": "bearer",
        "user": UserResponse.from_orm(target_user),
        "admin_switch": True
    }


# ============================================================================
# API Key Management
# ============================================================================

@router.post("/api-key/create")
async def create_api_key(current_user: User = Depends(require_user), db: Session = Depends(get_db)):
    """
    Generate new API key for programmatic access
    
    Hebrew: יצור מפתח API חדש
    """
    # Generate API key
    api_key = f"algogpt_{secrets.token_urlsafe(32)}"
    
    current_user.api_key = api_key
    db.commit()
    
    logger.info(f"✅ API key created for {current_user.username}")
    
    return {
        "api_key": api_key,
        "warning": "Save this key securely. You won't see it again!"
    }


@router.delete("/api-key/revoke")
async def revoke_api_key(current_user: User = Depends(require_user), db: Session = Depends(get_db)):
    """
    Revoke current API key
    
    Hebrew: הנל מפתח API
    """
    current_user.api_key = None
    db.commit()
    
    logger.info(f"✅ API key revoked for {current_user.username}")
    
    return {"status": "API key revoked"}


# ============================================================================
# User Management (Admin Only)
# ============================================================================

@router.get("/users")
async def list_users(admin_user: User = Depends(require_admin), db: Session = Depends(get_db)):
    """
    List all users (admin only)
    
    Hebrew: רשימת כל המשתמשים
    """
    users = db.query(User).all()
    return [UserResponse.from_orm(u) for u in users]


@router.patch("/users/{user_id}")
async def update_user(
    user_id: str,
    role: Optional[str] = None,
    is_active: Optional[bool] = None,
    admin_user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """
    Update user role/status (admin only)
    
    Hebrew: עדכן תפקיד/סטטוס משתמש
    """
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    if role:
        user.role = role
    if is_active is not None:
        user.is_active = is_active
    
    db.commit()
    db.refresh(user)
    
    logger.info(f"✅ User {user.username} updated by admin {admin_user.username}")
    
    return UserResponse.from_orm(user)


# ============================================================================
# Current User Info
# ============================================================================

@router.get("/me", response_model=UserResponse)
async def get_current_user(current_user: User = Depends(require_viewer)):
    """
    Get current logged-in user info
    
    Hebrew: קבל פרטי המשתמש הנוכחי
    """
    return UserResponse.from_orm(current_user)
