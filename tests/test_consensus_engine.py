"""
Test Consensus Engine
"""
import pytest
from algo_core.consensus_engine import ConsensusEngine

@pytest.fixture
def engine():
    return ConsensusEngine()

def test_merge_empty(engine):
    """Test merging empty data"""
    result = engine.merge([], [])
    assert result == []

def test_merge_scans(engine):
    """Test merging scan data"""
    scans = [
        {
            "source": "Cryptohopper",
            "data": [
                {"symbol": "BTCUSDT", "score": 8},
                {"symbol": "ETHUSDT", "score": 6}
            ]
        }
    ]
    
    result = engine.merge(scans, [])
    assert len(result) >= 1
    assert result[0]["symbol"] in ["BTCUSDT", "ETHUSDT"]

def test_merge_signals(engine):
    """Test merging signals"""
    signals = [
        {"symbol": "SOLUSDT", "score": 9, "source": "TradingView"},
        {"symbol": "ADAUSDT", "score": 7, "source": "Bybit"}
    ]
    
    result = engine.merge([], signals)
    assert len(result) >= 1

def test_score_ranking(engine):
    """Test that high scores rank first"""
    scans = [
        {
            "source": "Cryptohopper",
            "data": [
                {"symbol": "BTCUSDT", "score": 3},
                {"symbol": "ETHUSDT", "score": 9}
            ]
        }
    ]
    
    result = engine.merge(scans, [])
    # ETHUSDT should be first (higher score)
    assert result[0]["symbol"] == "ETHUSDT"
    assert result[1]["symbol"] == "BTCUSDT"
