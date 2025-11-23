"""Tests for Auto-Hedge Engine"""
import pytest
from engine.auto_hedge import AutoHedge, HedgeState

@pytest.mark.asyncio
async def test_hedge_init():
    """Test AutoHedge initialization"""
    hedge = AutoHedge()
    assert hedge.current_state == HedgeState.INACTIVE

@pytest.mark.asyncio
async def test_hedge_activation():
    """Test hedge activation"""
    hedge = AutoHedge()
    # Would activate if conditions met
    assert not await hedge.should_hedge()

@pytest.mark.asyncio
async def test_hedge_unwind():
    """Test hedge unwinding"""
    hedge = AutoHedge()
    hedge.current_state = HedgeState.ACTIVE
    assert await hedge.check_unwind() == False  # No exposure yet
