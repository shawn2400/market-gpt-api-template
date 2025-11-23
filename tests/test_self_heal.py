"""Tests for Self-Heal Engine"""
import pytest
from engine.self_heal import SelfHeal, IssueType

@pytest.mark.asyncio
async def test_self_heal_init():
    """Test SelfHeal initialization"""
    heal = SelfHeal()
    assert len(heal.active_issues) == 0

@pytest.mark.asyncio
async def test_detect_issue():
    """Test issue detection"""
    heal = SelfHeal()
    result = await heal.detect_issue(IssueType.API_FAILURE)
    assert result == True
    assert len(heal.active_issues) == 1

@pytest.mark.asyncio
async def test_cleanup_resolved():
    """Test cleanup of resolved issues"""
    heal = SelfHeal()
    await heal.detect_issue(IssueType.API_FAILURE)
    # Mark as resolved
    for issue in heal.active_issues.values():
        issue['resolved'] = True
    await heal.cleanup_resolved()
    assert len(heal.active_issues) == 0
