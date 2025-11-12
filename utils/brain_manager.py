#!/usr/bin/env python3
"""
Brain Manager - Dynamic AI Brain Management System
===================================================
Manages multiple AI providers with:
- Auto-suspend on failures (429, timeout, API errors)
- Auto-resume when API recovers
- Token budgeting and cost tracking
- Dynamic consensus threshold adjustment

Brains Configuration (2-Brain Consensus):
1. DeepSeek Chat - Ultra-cheap, reliable ($0.0001/call) ✅ ACTIVE
2. Qwen 2.5 Turbo - FREE, fast (Alibaba Cloud) ✅ ACTIVE

Optional Brains (SUSPENDED - can be enabled):
3. Gemini 2 Pro - Ultra-cheap, multi-modal ($0.00005/call)
4. Grok (XAI) - Optional fallback
5. Claude Sonnet - High quality ($0.003/call)
"""

import logging
import asyncio
from typing import Dict, Any, List, Optional, Callable
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger("algogpt.brain_manager")


class BrainStatus(Enum):
    """Brain operational status"""
    ACTIVE = "active"
    SUSPENDED = "suspended"
    DISABLED = "disabled"


@dataclass
class BrainConfig:
    """Configuration for a single AI brain"""
    name: str
    provider: str
    model: str
    cost_per_call: float
    max_tokens: int = 300
    status: BrainStatus = BrainStatus.ACTIVE
    enabled_env_var: str = ""
    call_function: Optional[Callable] = None
    
    failure_count: int = 0
    success_count: int = 0
    total_tokens: int = 0
    total_cost: float = 0.0
    last_failure: Optional[datetime] = None
    last_success: Optional[datetime] = None
    suspend_until: Optional[datetime] = None


class BrainManager:
    """
    Manages AI brains with auto-suspend/resume and cost tracking
    """
    
    def __init__(self):
        self.brains: Dict[str, BrainConfig] = {}
        self.logger = logging.getLogger("algogpt.brain_manager")
        self._initialize_brains()
    
    def _initialize_brains(self):
        """Initialize available AI brains"""
        try:
            from utils.llm_client import llm_chat_completion
            from utils.qwen_client import call_qwen, ENABLE_QWEN
            from utils.gemini_client import call_gemini, ENABLE_GEMINI
            from utils.xai_client import call_xai, ENABLE_XAI
            
            self.brains = {
                "deepseek": BrainConfig(
                    name="DeepSeek Chat",
                    provider="deepseek",
                    model="deepseek-chat",
                    cost_per_call=0.0001,
                    max_tokens=300,
                    status=BrainStatus.ACTIVE,
                    call_function=llm_chat_completion
                ),
                "qwen": BrainConfig(
                    name="Qwen 2.5 Turbo",
                    provider="qwen",
                    model="qwen-turbo",
                    cost_per_call=0.0,
                    max_tokens=300,
                    status=BrainStatus.ACTIVE if ENABLE_QWEN else BrainStatus.DISABLED,
                    enabled_env_var="ENABLE_QWEN",
                    call_function=call_qwen
                ),
                "gemini": BrainConfig(
                    name="Gemini 2 Pro",
                    provider="gemini",
                    model="gemini-2.0-flash-exp",
                    cost_per_call=0.00005,
                    max_tokens=300,
                    status=BrainStatus.SUSPENDED,
                    enabled_env_var="ENABLE_GEMINI",
                    call_function=call_gemini
                ),
                "grok": BrainConfig(
                    name="Grok (XAI)",
                    provider="xai",
                    model="grok-2-latest",
                    cost_per_call=0.001,
                    max_tokens=300,
                    status=BrainStatus.SUSPENDED,
                    enabled_env_var="ENABLE_XAI",
                    call_function=call_xai
                )
            }
            
            active_count = self.get_active_count()
            self.logger.info(f"🧠 Brain Manager initialized: {active_count} active brains")
            
        except ImportError as e:
            self.logger.error(f"Failed to import AI clients: {e}")
    
    def get_active_brains(self) -> List[str]:
        """Get list of currently active brain IDs"""
        return [
            brain_id for brain_id, brain in self.brains.items()
            if brain.status == BrainStatus.ACTIVE
        ]
    
    def get_active_count(self) -> int:
        """Get count of active brains"""
        return len(self.get_active_brains())
    
    def get_consensus_threshold(self) -> int:
        """
        Get required votes for consensus based on active brains
        
        Returns:
            Required votes (always ceil(active_count * 2/3))
        """
        active_count = self.get_active_count()
        if active_count == 0:
            return 1
        
        import math
        return math.ceil(active_count * 2 / 3)
    
    def suspend_brain(self, brain_id: str, reason: str = "API failure", duration_minutes: int = 60):
        """
        Suspend a brain temporarily
        
        Args:
            brain_id: Brain identifier
            reason: Reason for suspension
            duration_minutes: How long to suspend (default 60 min)
        """
        if brain_id not in self.brains:
            return
        
        brain = self.brains[brain_id]
        brain.status = BrainStatus.SUSPENDED
        brain.failure_count += 1
        brain.last_failure = datetime.now()
        brain.suspend_until = datetime.now() + timedelta(minutes=duration_minutes)
        
        active_count = self.get_active_count()
        threshold = self.get_consensus_threshold()
        
        self.logger.warning(
            f"⚠️ Brain suspended: {brain.name} - Reason: {reason} - "
            f"Resume at: {brain.suspend_until.strftime('%H:%M')} - "
            f"Active brains: {active_count} - Consensus: {threshold}/{active_count}"
        )
    
    def resume_brain(self, brain_id: str):
        """
        Resume a suspended brain
        
        Args:
            brain_id: Brain identifier
        """
        if brain_id not in self.brains:
            return
        
        brain = self.brains[brain_id]
        if brain.status == BrainStatus.SUSPENDED:
            brain.status = BrainStatus.ACTIVE
            brain.suspend_until = None
            
            active_count = self.get_active_count()
            threshold = self.get_consensus_threshold()
            
            self.logger.info(
                f"✅ Brain resumed: {brain.name} - "
                f"Active brains: {active_count} - Consensus: {threshold}/{active_count}"
            )
    
    def check_auto_resume(self):
        """Check if any suspended brains should be auto-resumed"""
        now = datetime.now()
        
        for brain_id, brain in self.brains.items():
            if brain.status == BrainStatus.SUSPENDED and brain.suspend_until:
                if now >= brain.suspend_until:
                    self.logger.info(f"🔄 Auto-resuming brain: {brain.name}")
                    self.resume_brain(brain_id)
    
    async def call_brain_vote(
        self,
        brain_id: str,
        brain_instance: Any,
        scout_data: Dict[str, Any],
        market_data: Dict[str, Any],
        wallet_state: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """
        Call a brain's vote method with auto-suspend on errors
        
        Args:
            brain_id: Brain identifier
            brain_instance: Brain instance to call
            scout_data: Scout analysis data
            market_data: Market indicators
            wallet_state: Wallet state
            
        Returns:
            Vote result dict or None on failure
        """
        if brain_id not in self.brains:
            self.logger.error(f"Unknown brain: {brain_id}")
            return None
        
        brain = self.brains[brain_id]
        
        if brain.status != BrainStatus.ACTIVE:
            self.logger.debug(f"Brain {brain.name} is {brain.status.value}, skipping")
            return None
        
        try:
            vote_result = await brain_instance.vote(scout_data, market_data, wallet_state)
            
            if vote_result and "vote" in vote_result:
                brain.success_count += 1
                brain.last_success = datetime.now()
                brain.total_cost += brain.cost_per_call
                
                self.logger.debug(
                    f"✅ {brain.name}: {vote_result['vote']} "
                    f"(Score: {vote_result.get('score', 0)}/10) - "
                    f"Success #{brain.success_count}"
                )
                return vote_result
            else:
                self.suspend_brain(brain_id, reason="Empty/invalid response", duration_minutes=30)
                return None
                
        except Exception as e:
            error_str = str(e)
            
            if "429" in error_str or "Too Many Requests" in error_str or "credits" in error_str.lower():
                self.suspend_brain(brain_id, reason="Rate limit/No credits", duration_minutes=120)
            elif "timeout" in error_str.lower():
                self.suspend_brain(brain_id, reason="Timeout", duration_minutes=30)
            elif "401" in error_str or "403" in error_str:
                self.suspend_brain(brain_id, reason="Auth error", duration_minutes=180)
            else:
                self.suspend_brain(brain_id, reason=f"Error: {error_str[:50]}", duration_minutes=60)
            
            return None
    
    async def call_brain(
        self,
        brain_id: str,
        prompt: str,
        system: Optional[str] = None,
        temperature: float = 0.3
    ) -> Optional[str]:
        """
        Call a specific brain with auto-suspend on errors (low-level API call)
        
        Args:
            brain_id: Brain identifier
            prompt: User prompt
            system: System instruction
            temperature: Sampling temperature
            
        Returns:
            AI response or None on failure
        """
        if brain_id not in self.brains:
            self.logger.error(f"Unknown brain: {brain_id}")
            return None
        
        brain = self.brains[brain_id]
        
        if brain.status != BrainStatus.ACTIVE:
            self.logger.debug(f"Brain {brain.name} is {brain.status.value}, skipping")
            return None
        
        if not brain.call_function:
            self.logger.error(f"Brain {brain.name} has no call function")
            return None
        
        try:
            response = await brain.call_function(
                prompt=prompt,
                system=system,
                temperature=temperature,
                max_tokens=brain.max_tokens
            )
            
            if response:
                brain.success_count += 1
                brain.last_success = datetime.now()
                brain.total_tokens += len(response.split())
                brain.total_cost += brain.cost_per_call
                
                self.logger.debug(f"✅ {brain.name}: Success ({brain.success_count} total)")
                return response
            else:
                self.suspend_brain(brain_id, reason="Empty response", duration_minutes=30)
                return None
                
        except Exception as e:
            error_str = str(e)
            
            if "429" in error_str or "Too Many Requests" in error_str:
                self.suspend_brain(brain_id, reason="Rate limit (429)", duration_minutes=120)
            elif "timeout" in error_str.lower():
                self.suspend_brain(brain_id, reason="Timeout", duration_minutes=30)
            elif "401" in error_str or "403" in error_str:
                self.suspend_brain(brain_id, reason="Auth error", duration_minutes=180)
            else:
                self.suspend_brain(brain_id, reason=f"Error: {error_str[:50]}", duration_minutes=60)
            
            return None
    
    async def call_all_active(
        self,
        prompt: str,
        system: Optional[str] = None,
        temperature: float = 0.3
    ) -> Dict[str, Optional[str]]:
        """
        Call all active brains in parallel
        
        Args:
            prompt: User prompt
            system: System instruction
            temperature: Sampling temperature
            
        Returns:
            Dict of brain_id -> response
        """
        self.check_auto_resume()
        
        active_brains = self.get_active_brains()
        
        if not active_brains:
            self.logger.error("❌ No active brains available!")
            return {}
        
        self.logger.info(f"🧠 Calling {len(active_brains)} active brains: {', '.join([self.brains[b].name for b in active_brains])}")
        
        tasks = {
            brain_id: self.call_brain(brain_id, prompt, system, temperature)
            for brain_id in active_brains
        }
        
        results = {}
        for brain_id, task in tasks.items():
            results[brain_id] = await task
        
        success_count = sum(1 for r in results.values() if r is not None)
        self.logger.info(f"📊 Brain responses: {success_count}/{len(active_brains)} successful")
        
        return results
    
    def get_stats(self) -> Dict[str, Any]:
        """Get statistics for all brains"""
        stats = {
            "total_brains": len(self.brains),
            "active_brains": self.get_active_count(),
            "consensus_threshold": self.get_consensus_threshold(),
            "brains": {}
        }
        
        for brain_id, brain in self.brains.items():
            stats["brains"][brain_id] = {
                "name": brain.name,
                "status": brain.status.value,
                "success_count": brain.success_count,
                "failure_count": brain.failure_count,
                "total_cost": f"${brain.total_cost:.6f}",
                "cost_per_call": f"${brain.cost_per_call:.6f}",
                "last_success": brain.last_success.isoformat() if brain.last_success else None,
                "suspend_until": brain.suspend_until.isoformat() if brain.suspend_until else None
            }
        
        return stats


_brain_manager_instance = None


def get_brain_manager() -> BrainManager:
    """Get singleton Brain Manager instance"""
    global _brain_manager_instance
    if _brain_manager_instance is None:
        _brain_manager_instance = BrainManager()
    return _brain_manager_instance


if __name__ == "__main__":
    import asyncio
    
    async def test_manager():
        manager = get_brain_manager()
        
        print("🧠 Brain Manager Test\n")
        stats = manager.get_stats()
        
        print(f"Total Brains: {stats['total_brains']}")
        print(f"Active Brains: {stats['active_brains']}")
        print(f"Consensus Threshold: {stats['consensus_threshold']}/{stats['active_brains']}\n")
        
        print("Brain Status:")
        for brain_id, brain_stats in stats['brains'].items():
            print(f"  - {brain_stats['name']}: {brain_stats['status']} (Cost: {brain_stats['cost_per_call']}/call)")
        
        print("\n✅ Brain Manager ready!")
    
    asyncio.run(test_manager())
