"""
Test Self Optimizer
"""
import pytest
from algo_core.self_optimizer import SelfOptimizer

@pytest.fixture
def optimizer():
    return SelfOptimizer()

def test_evaluate_empty(optimizer):
    """Test evaluating empty results"""
    scores = optimizer.evaluate([])
    assert scores == {}

def test_evaluate_single_win(optimizer):
    """Test single winning trade"""
    results = [
        {"source": "cryptohopper", "outcome": 1}
    ]
    scores = optimizer.evaluate(results)
    assert scores["cryptohopper"] == 10.0

def test_evaluate_mixed_results(optimizer):
    """Test mixed win/loss"""
    results = [
        {"source": "cryptohopper", "outcome": 1},
        {"source": "cryptohopper", "outcome": 0},
        {"source": "cryptohopper", "outcome": 1},
    ]
    scores = optimizer.evaluate(results)
    expected = (2 / 3) * 10  # 66.67
    assert abs(scores["cryptohopper"] - expected) < 0.1

def test_evaluate_multiple_bots(optimizer):
    """Test scoring multiple bots"""
    results = [
        {"source": "cryptohopper", "outcome": 1},
        {"source": "3commas", "outcome": 0},
        {"source": "cryptohopper", "outcome": 1},
        {"source": "3commas", "outcome": 0},
    ]
    scores = optimizer.evaluate(results)
    
    assert scores["cryptohopper"] > scores["3commas"]
    assert scores["cryptohopper"] == 10.0
    assert scores["3commas"] == 0.0
