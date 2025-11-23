"""Tests for Profit-Share Billing"""
import pytest
from typing import Optional
from engine.profit_share import ProfitShare

@pytest.mark.asyncio
async def test_profit_share_init():
    """Test ProfitShare initialization"""
    profit_share = ProfitShare()
    assert profit_share.profit_share_rate == 0.18

@pytest.mark.asyncio
async def test_profit_share_mark_paid():
    """Test marking billing as paid"""
    profit_share = ProfitShare()
    await profit_share.create_new_billing()
    profit_share.current_billing['due_amount'] = 100
    result = await profit_share.mark_paid(100)
    assert profit_share.current_billing['paid'] == True

@pytest.mark.asyncio
async def test_overdue_check():
    """Test overdue checking"""
    profit_share = ProfitShare()
    overdue = await profit_share.check_overdue()
    assert overdue == False  # No billing yet
