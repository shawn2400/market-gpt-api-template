"""Tests for Exchange Balancer"""
import pytest
from engine.exchange_balancer import ExchangeBalancer, ExchangeStatus

@pytest.mark.asyncio
async def test_balancer_init():
    """Test ExchangeBalancer initialization"""
    balancer = ExchangeBalancer()
    assert balancer.primary == 'binance'
    assert balancer.secondary == 'bybit'

@pytest.mark.asyncio
async def test_get_active_exchange():
    """Test getting active exchange"""
    balancer = ExchangeBalancer()
    exchange = await balancer.get_active_exchange()
    assert exchange in ['binance', 'bybit']

@pytest.mark.asyncio
async def test_exchange_freeze():
    """Test freezing exchange"""
    balancer = ExchangeBalancer()
    await balancer.freeze_exchange('binance')
    assert balancer.exchanges['binance']['status'] == ExchangeStatus.FROZEN
