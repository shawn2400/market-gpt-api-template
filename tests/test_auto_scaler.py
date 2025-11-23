"""Tests for Auto-Scaler"""
import pytest
from engine.auto_scaler import AutoScaler, ScalingMode

@pytest.mark.asyncio
async def test_scaler_init():
    """Test AutoScaler initialization"""
    scaler = AutoScaler()
    assert scaler.current_mode == ScalingMode.NORMAL
    assert scaler.current_size_multiplier == 1.0

@pytest.mark.asyncio
async def test_scaler_freeze():
    """Test scaler freeze"""
    scaler = AutoScaler()
    await scaler.freeze()
    assert scaler.current_mode == ScalingMode.FROZEN

@pytest.mark.asyncio
async def test_scaler_reset():
    """Test scaler reset"""
    scaler = AutoScaler()
    scaler.current_mode = ScalingMode.BOOST
    await scaler.reset_to_normal()
    assert scaler.current_mode == ScalingMode.NORMAL
