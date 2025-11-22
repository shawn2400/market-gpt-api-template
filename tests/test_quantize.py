"""
Quantize utility tests
"""
import math
from utils.quantize import (
    quantize_price,
    quantize_qty,
    ensure_min_qty,
    ensure_min_notional,
    clamp_decimals,
)

# Test fixtures (stable for testing)
F = {"tick": 0.01, "step": 0.001, "minQty": 0.001, "minNotional": 5.0}


def test_quantize_price_floor():
    """Test price quantization - floor mode"""
    result1 = quantize_price(100.007, F, "down")
    assert math.isclose(result1, 100.00, abs_tol=0.001)
    
    result2 = quantize_price(100.019, F, "down")
    assert math.isclose(result2, 100.01, abs_tol=0.001)


def test_quantize_price_up():
    """Test price quantization - up mode"""
    result = quantize_price(100.001, F, "up")
    assert math.isclose(result, 100.01, abs_tol=0.001)


def test_quantize_price_nearest():
    """Test price quantization - nearest mode"""
    result = quantize_price(100.015, F, "nearest")
    # Python uses banker's rounding - 100.005 may round to 100.0 or 100.01
    # Use 100.015 which clearly should round to 100.02
    assert math.isclose(result, 100.02, abs_tol=0.005)


def test_quantize_qty_floor():
    """Test quantity quantization"""
    result1 = quantize_qty(0.0019, F)
    assert math.isclose(result1, 0.001, abs_tol=0.0001)
    
    result2 = quantize_qty(0.0574, F)
    assert math.isclose(result2, 0.057, abs_tol=0.0001)


def test_ensure_min_qty():
    """Test minimum quantity enforcement"""
    result1 = ensure_min_qty(0.0, F)
    assert math.isclose(result1, 0.001, abs_tol=0.0001)
    
    result2 = ensure_min_qty(0.0004, F)
    assert math.isclose(result2, 0.001, abs_tol=0.0001)
    
    result3 = ensure_min_qty(0.0022, F)
    assert math.isclose(result3, 0.002, abs_tol=0.0001)


def test_ensure_min_notional():
    """Test minimum notional enforcement"""
    result1 = ensure_min_notional(0.1, 10.0, F)
    assert math.isclose(result1, 0.5, abs_tol=0.01)
    
    result2 = ensure_min_notional(1.2345, 10.0, F)
    assert math.isclose(result2, 1.234, abs_tol=0.001)


def test_clamp_decimals():
    """Test decimal clamping"""
    v = clamp_decimals(1.234567, 3)
    # Allow floating point tolerance
    assert math.isclose(v, 1.235, abs_tol=1e-6)
