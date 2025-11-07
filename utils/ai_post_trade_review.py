#!/usr/bin/env python3
# utils/ai_post_trade_review.py
"""
AI Post-Trade Review - Multi-Brain Analysis
==========================================
Sends completed trades to all 5 AI brains for scoring:
- GPT-5 (OpenAI)
- Gemini 2 Pro (Google)
- DeepSeek Chat
- Grok (AI-X)
- Claude Sonnet 3.5

Each brain scores 4 categories (0-100):
1. Entry Quality
2. SL/TP Placement
3. Position Management
4. Exit Timing
"""
import os
import logging
import asyncio
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, asdict
import json
import httpx
from pathlib import Path

logger = logging.getLogger("algogpt.ai_post_trade_review")

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "").strip()
XAI_API_KEY = os.getenv("XAI_API_KEY", "").strip()
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "").strip()

OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-5-2025-08-07")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.0-flash-exp")
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
XAI_MODEL = os.getenv("XAI_MODEL", "grok-2-latest")
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-5")

REVIEW_DIR = Path("data/ai_reviews")
REVIEW_DIR.mkdir(parents=True, exist_ok=True)


@dataclass
class AIBrainScore:
    brain_name: str
    entry_quality: int  # 0-100
    sltp_placement: int  # 0-100
    position_management: int  # 0-100
    exit_timing: int  # 0-100
    overall_score: float  # Average
    comments: str
    suggestions: List[str]
    response_time_ms: float
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class TradeReviewResult:
    trade_id: str
    symbol: str
    timestamp: float
    scores: List[AIBrainScore]
    consensus_score: float
    top_suggestions: List[str]
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class AIPostTradeReviewer:
    """Reviews completed trades with all 5 AI brains"""
    
    def __init__(self):
        self.timeout = httpx.Timeout(60.0)
    
    async def review_trade(self, trade_data: Dict[str, Any]) -> TradeReviewResult:
        """Send trade to all brains for review"""
        trade_id = trade_data.get("trade_id", f"{trade_data['symbol']}_{int(trade_data.get('exit_time', 0))}")
        
        logger.info(f"Starting AI review for trade: {trade_id}")
        
        review_prompt = self._build_review_prompt(trade_data)
        
        tasks = []
        if OPENAI_API_KEY:
            tasks.append(self._review_with_openai(review_prompt))
        if GEMINI_API_KEY:
            tasks.append(self._review_with_gemini(review_prompt))
        if DEEPSEEK_API_KEY:
            tasks.append(self._review_with_deepseek(review_prompt))
        if XAI_API_KEY:
            tasks.append(self._review_with_grok(review_prompt))
        if ANTHROPIC_API_KEY:
            tasks.append(self._review_with_claude(review_prompt))
        
        scores = await asyncio.gather(*tasks, return_exceptions=True)
        
        valid_scores = [s for s in scores if isinstance(s, AIBrainScore)]
        
        if not valid_scores:
            logger.error(f"No valid scores for trade {trade_id}")
            return TradeReviewResult(
                trade_id=trade_id,
                symbol=trade_data["symbol"],
                timestamp=trade_data.get("exit_time", 0),
                scores=[],
                consensus_score=0.0,
                top_suggestions=[]
            )
        
        consensus_score = sum(s.overall_score for s in valid_scores) / len(valid_scores)
        
        all_suggestions = []
        for score in valid_scores:
            all_suggestions.extend(score.suggestions)
        
        suggestion_counts = {}
        for suggestion in all_suggestions:
            suggestion_counts[suggestion] = suggestion_counts.get(suggestion, 0) + 1
        
        top_suggestions = sorted(suggestion_counts.items(), key=lambda x: x[1], reverse=True)[:5]
        top_suggestions = [s[0] for s in top_suggestions]
        
        result = TradeReviewResult(
            trade_id=trade_id,
            symbol=trade_data["symbol"],
            timestamp=trade_data.get("exit_time", 0),
            scores=valid_scores,
            consensus_score=consensus_score,
            top_suggestions=top_suggestions
        )
        
        self._save_review(result)
        
        logger.info(f"AI review complete: {trade_id} - Consensus: {consensus_score:.1f}/100")
        
        return result
    
    def _build_review_prompt(self, trade: Dict[str, Any]) -> str:
        """Build standardized review prompt"""
        duration_min = int((trade.get("exit_time", 0) - trade.get("entry_time", 0)) / 60)
        
        return f"""Analyze this completed crypto futures trade and provide scores (0-100) for each category:

**Trade Details:**
- Symbol: {trade.get("symbol")}
- Side: {trade.get("side")}
- Entry Price: ${trade.get("entry_price", 0):.4f}
- Exit Price: ${trade.get("exit_price", 0):.4f}
- SL Price: ${trade.get("sl_price", 0):.4f}
- TP Prices: {trade.get("tp_prices", [])}
- Quantity: {trade.get("quantity", 0)}
- Leverage: {trade.get("leverage", 1)}x
- PnL: ${trade.get("pnl_usd", 0):.2f} ({trade.get("pnl_pct", 0):.2f}%)
- Duration: {duration_min} minutes
- Exit Reason: {trade.get("exit_reason")}
- Market Regime: {trade.get("regime", "UNKNOWN")}

Provide a JSON response with:
{{
  "entry_quality": <0-100>,
  "sltp_placement": <0-100>,
  "position_management": <0-100>,
  "exit_timing": <0-100>,
  "comments": "<brief analysis>",
  "suggestions": ["<improvement 1>", "<improvement 2>", ...]
}}

Be critical and actionable. Focus on what could be improved."""
    
    async def _review_with_openai(self, prompt: str) -> AIBrainScore:
        """Get review from GPT-5"""
        import time as _t
        start = _t.time()
        
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(
                    "https://api.openai.com/v1/chat/completions",
                    headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
                    json={
                        "model": OPENAI_MODEL,
                        "messages": [
                            {"role": "system", "content": "You are a professional crypto trading analyst. Provide critical, actionable feedback."},
                            {"role": "user", "content": prompt}
                        ],
                        "temperature": 0.3,
                        "max_completion_tokens": 500
                    }
                )
                resp.raise_for_status()
                data = resp.json()
                content = data["choices"][0]["message"]["content"]
                
                result = self._parse_review_response(content)
                
                return AIBrainScore(
                    brain_name="GPT-5",
                    entry_quality=result["entry_quality"],
                    sltp_placement=result["sltp_placement"],
                    position_management=result["position_management"],
                    exit_timing=result["exit_timing"],
                    overall_score=(result["entry_quality"] + result["sltp_placement"] + 
                                  result["position_management"] + result["exit_timing"]) / 4,
                    comments=result["comments"],
                    suggestions=result["suggestions"],
                    response_time_ms=(_t.time() - start) * 1000
                )
        except Exception as e:
            logger.error(f"GPT-5 review failed: {e}")
            raise
    
    async def _review_with_gemini(self, prompt: str) -> AIBrainScore:
        """Get review from Gemini 2 Pro"""
        import time as _t
        start = _t.time()
        
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(
                    f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}",
                    json={
                        "contents": [{
                            "parts": [{"text": prompt}]
                        }],
                        "generationConfig": {
                            "temperature": 0.3,
                            "maxOutputTokens": 500
                        }
                    }
                )
                resp.raise_for_status()
                data = resp.json()
                content = data["candidates"][0]["content"]["parts"][0]["text"]
                
                result = self._parse_review_response(content)
                
                return AIBrainScore(
                    brain_name="Gemini-2-Pro",
                    entry_quality=result["entry_quality"],
                    sltp_placement=result["sltp_placement"],
                    position_management=result["position_management"],
                    exit_timing=result["exit_timing"],
                    overall_score=(result["entry_quality"] + result["sltp_placement"] + 
                                  result["position_management"] + result["exit_timing"]) / 4,
                    comments=result["comments"],
                    suggestions=result["suggestions"],
                    response_time_ms=(_t.time() - start) * 1000
                )
        except Exception as e:
            logger.error(f"Gemini review failed: {e}")
            raise
    
    async def _review_with_deepseek(self, prompt: str) -> AIBrainScore:
        """Get review from DeepSeek"""
        import time as _t
        start = _t.time()
        
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(
                    "https://api.deepseek.com/v1/chat/completions",
                    headers={"Authorization": f"Bearer {DEEPSEEK_API_KEY}"},
                    json={
                        "model": DEEPSEEK_MODEL,
                        "messages": [
                            {"role": "system", "content": "You are a professional crypto trading analyst."},
                            {"role": "user", "content": prompt}
                        ],
                        "temperature": 0.3,
                        "max_tokens": 500
                    }
                )
                resp.raise_for_status()
                data = resp.json()
                content = data["choices"][0]["message"]["content"]
                
                result = self._parse_review_response(content)
                
                return AIBrainScore(
                    brain_name="DeepSeek",
                    entry_quality=result["entry_quality"],
                    sltp_placement=result["sltp_placement"],
                    position_management=result["position_management"],
                    exit_timing=result["exit_timing"],
                    overall_score=(result["entry_quality"] + result["sltp_placement"] + 
                                  result["position_management"] + result["exit_timing"]) / 4,
                    comments=result["comments"],
                    suggestions=result["suggestions"],
                    response_time_ms=(_t.time() - start) * 1000
                )
        except Exception as e:
            logger.error(f"DeepSeek review failed: {e}")
            raise
    
    async def _review_with_grok(self, prompt: str) -> AIBrainScore:
        """Get review from Grok"""
        import time as _t
        start = _t.time()
        
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(
                    "https://api.x.ai/v1/chat/completions",
                    headers={"Authorization": f"Bearer {XAI_API_KEY}"},
                    json={
                        "model": XAI_MODEL,
                        "messages": [
                            {"role": "system", "content": "You are a professional crypto trading analyst."},
                            {"role": "user", "content": prompt}
                        ],
                        "temperature": 0.3,
                        "max_tokens": 500
                    }
                )
                resp.raise_for_status()
                data = resp.json()
                content = data["choices"][0]["message"]["content"]
                
                result = self._parse_review_response(content)
                
                return AIBrainScore(
                    brain_name="Grok",
                    entry_quality=result["entry_quality"],
                    sltp_placement=result["sltp_placement"],
                    position_management=result["position_management"],
                    exit_timing=result["exit_timing"],
                    overall_score=(result["entry_quality"] + result["sltp_placement"] + 
                                  result["position_management"] + result["exit_timing"]) / 4,
                    comments=result["comments"],
                    suggestions=result["suggestions"],
                    response_time_ms=(_t.time() - start) * 1000
                )
        except Exception as e:
            logger.error(f"Grok review failed: {e}")
            raise
    
    async def _review_with_claude(self, prompt: str) -> AIBrainScore:
        """Get review from Claude"""
        import time as _t
        start = _t.time()
        
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(
                    "https://api.anthropic.com/v1/messages",
                    headers={
                        "x-api-key": ANTHROPIC_API_KEY,
                        "anthropic-version": "2023-06-01",
                        "content-type": "application/json"
                    },
                    json={
                        "model": CLAUDE_MODEL,
                        "max_tokens": 500,
                        "messages": [
                            {"role": "user", "content": prompt}
                        ]
                    }
                )
                resp.raise_for_status()
                data = resp.json()
                content = data["content"][0]["text"]
                
                result = self._parse_review_response(content)
                
                return AIBrainScore(
                    brain_name="Claude-3.5",
                    entry_quality=result["entry_quality"],
                    sltp_placement=result["sltp_placement"],
                    position_management=result["position_management"],
                    exit_timing=result["exit_timing"],
                    overall_score=(result["entry_quality"] + result["sltp_placement"] + 
                                  result["position_management"] + result["exit_timing"]) / 4,
                    comments=result["comments"],
                    suggestions=result["suggestions"],
                    response_time_ms=(_t.time() - start) * 1000
                )
        except Exception as e:
            logger.error(f"Claude review failed: {e}")
            raise
    
    def _parse_review_response(self, content: str) -> Dict[str, Any]:
        """Parse AI response into structured format"""
        try:
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                content = content.split("```")[1].split("```")[0].strip()
            
            data = json.loads(content)
            
            return {
                "entry_quality": int(data.get("entry_quality", 50)),
                "sltp_placement": int(data.get("sltp_placement", 50)),
                "position_management": int(data.get("position_management", 50)),
                "exit_timing": int(data.get("exit_timing", 50)),
                "comments": str(data.get("comments", "")),
                "suggestions": data.get("suggestions", [])
            }
        except Exception as e:
            logger.error(f"Failed to parse review response: {e}")
            return {
                "entry_quality": 50,
                "sltp_placement": 50,
                "position_management": 50,
                "exit_timing": 50,
                "comments": "Failed to parse",
                "suggestions": []
            }
    
    def _save_review(self, result: TradeReviewResult):
        """Save review to disk"""
        try:
            filename = REVIEW_DIR / f"{result.trade_id}_review.json"
            with open(filename, 'w') as f:
                json.dump(result.to_dict(), f, indent=2)
            logger.info(f"Review saved: {filename}")
        except Exception as e:
            logger.error(f"Failed to save review: {e}")


_reviewer = AIPostTradeReviewer()


async def review_completed_trade(trade_data: Dict[str, Any]) -> TradeReviewResult:
    """Review a completed trade with all AI brains"""
    return await _reviewer.review_trade(trade_data)
