# routes/dashboard.py
# -*- coding: utf-8 -*-
"""
בס"ד
Dynamic Presentation Dashboard API
Auto-updates with live system data from trades, AI mesh, news sources, performance metrics
"""
from __future__ import annotations
import os
import time
import asyncio
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Header, HTTPException, WebSocket, WebSocketDisconnect
from contextlib import suppress
import logging

from utils.ws_fallback import LAST_PRICE_CACHE
from utils.watchlist_utils import load_watchlist

logger = logging.getLogger("algogpt.dashboard")

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])

_API_BEARER_TOKEN = (os.getenv("API_BEARER_TOKEN") or os.getenv("API_TOKEN") or "").strip()


@router.get("/", summary="Dashboard snapshot")
async def dashboard_snapshot():
    """
    מחזיר Snapshot כללי לדשבורד:
    - Watchlist
    - מחירים אחרונים (WS)
    """
    now = time.time()

    # --- Load watchlist
    watchlist = load_watchlist()

    # --- Last prices snapshot
    last_prices = []
    for sym, price_tuple in LAST_PRICE_CACHE.items():
        price, ts_ms = price_tuple
        ts = ts_ms / 1000.0
        age_sec = round(now - ts, 2) if ts else None
        last_prices.append({
            "symbol": sym,
            "price": price,
            "ts": ts,
            "age_sec": age_sec,
            "fresh": age_sec is not None and age_sec <= 10
        })

    return {
        "ok": True,
        "watchlist": watchlist,
        "last_prices": last_prices,
        "count_symbols": len(last_prices),
        "ts": now
    }

def _auth_ok(auth_header: str) -> bool:
    """Check Bearer token authorization"""
    if not _API_BEARER_TOKEN:
        return True
    if not (auth_header and auth_header.startswith("Bearer ")):
        return False
    tok = auth_header.split(" ", 1)[1].strip()
    return tok == _API_BEARER_TOKEN

def _get_system_uptime() -> Dict[str, Any]:
    """Calculate system uptime"""
    try:
        with open('/proc/uptime', 'r') as f:
            uptime_seconds = float(f.readline().split()[0])
        return {
            "uptime_seconds": int(uptime_seconds),
            "uptime_hours": round(uptime_seconds / 3600, 2),
            "uptime_days": round(uptime_seconds / 86400, 2)
        }
    except:
        return {"uptime_seconds": 0, "uptime_hours": 0, "uptime_days": 0}

def _get_ai_mesh_config() -> List[Dict[str, Any]]:
    """Return 8-AI mesh configuration with weights"""
    return [
        {"name": "Claude Sonnet 4.5", "provider": "Anthropic", "weight": 45, "status": "active", "model": "claude-sonnet-4.5"},
        {"name": "Perplexity", "provider": "Perplexity", "weight": 25, "status": "active", "model": "sonar-reasoning"},
        {"name": "Cohere", "provider": "Cohere", "weight": 20, "status": "planned", "model": "command-r-plus"},
        {"name": "Mistral", "provider": "Mistral", "weight": 10, "status": "planned", "model": "mistral-large-2"},
        {"name": "Groq", "provider": "Groq", "weight": 0, "status": "planned", "model": "llama-3.3-70b"},
        {"name": "Gemini", "provider": "Google", "weight": 0, "status": "planned", "model": "gemini-2.0-flash"},
        {"name": "Voyage AI", "provider": "Voyage", "weight": 0, "status": "planned", "model": "voyage-3"},
        {"name": "AI-X (Grok)", "provider": "xAI", "weight": 0, "status": "planned", "model": "grok-2"}
    ]

def _get_news_sources() -> List[Dict[str, Any]]:
    """Return 10 news sources configuration"""
    return [
        {"name": "TradingView", "type": "alerts", "status": "active", "category": "Technical Analysis"},
        {"name": "N8N Workflows", "type": "automation", "status": "active", "category": "Integration"},
        {"name": "Telegram Bot", "type": "messaging", "status": "active", "category": "Communication"},
        {"name": "CoinDesk", "type": "news", "status": "planned", "category": "Crypto News"},
        {"name": "Bloomberg", "type": "news", "status": "planned", "category": "Financial News"},
        {"name": "CoinTelegraph", "type": "news", "status": "planned", "category": "Crypto News"},
        {"name": "Twitter/X", "type": "social", "status": "planned", "category": "Social Sentiment"},
        {"name": "Reddit", "type": "social", "status": "planned", "category": "Community Sentiment"},
        {"name": "Binance Announcements", "type": "exchange", "status": "planned", "category": "Exchange Updates"},
        {"name": "Fear & Greed Index", "type": "indicator", "status": "planned", "category": "Market Sentiment"}
    ]

def _get_benchmarking_engines() -> List[Dict[str, Any]]:
    """Return 8 benchmarking/backtesting engines"""
    return [
        {"name": "Freqtrade", "language": "Python", "status": "planned", "use_case": "Crypto Bot Framework"},
        {"name": "LEAN", "language": "C#/Python", "status": "planned", "use_case": "Institutional Quant Platform"},
        {"name": "Backtrader", "language": "Python", "status": "planned", "use_case": "Strategy Backtesting"},
        {"name": "Jesse", "language": "Python", "status": "planned", "use_case": "Crypto Live Trading"},
        {"name": "VectorBT", "language": "Python", "status": "planned", "use_case": "Fast Vectorized Backtesting"},
        {"name": "Zipline", "language": "Python", "status": "planned", "use_case": "Algorithmic Trading Library"},
        {"name": "QuantConnect", "language": "C#/Python", "status": "planned", "use_case": "Cloud Quant Platform"},
        {"name": "Custom AlgoGPT", "language": "Python", "status": "active", "use_case": "Internal Benchmarking"}
    ]

def _get_budget_analysis() -> Dict[str, Any]:
    """Return budget breakdown for 4GB vs 8GB hosting"""
    return {
        "options": [
            {
                "name": "4GB Server (Basic)",
                "ram": "4GB",
                "monthly_cost_usd": 182,
                "features": ["2 vCPU", "40GB SSD", "Basic scalability"],
                "recommended": False
            },
            {
                "name": "8GB Server (Recommended)",
                "ram": "8GB",
                "monthly_cost_usd": 470,
                "features": ["4 vCPU", "80GB SSD", "High performance", "Multi-tenant ready", "AI Mesh capable"],
                "recommended": True
            }
        ],
        "additional_costs": {
            "github_pro": 4,
            "openai_api": 50,
            "ai_mesh_apis": 100,
            "news_apis": 30,
            "total_estimated_monthly": 654
        }
    }

def _get_roadmap_summary() -> Dict[str, Any]:
    """Return ROADMAP summary with progress"""
    return {
        "total_weeks": 12,
        "total_tasks": 113,
        "phases": [
            {"phase": 1, "name": "Foundation & Web Dashboard", "weeks": "1-3", "tasks": 25, "status": "in_progress"},
            {"phase": 2, "name": "8-AI Mesh Integration", "weeks": "4-6", "tasks": 30, "status": "planned"},
            {"phase": 3, "name": "News & Multi-Tenant", "weeks": "7-9", "tasks": 28, "status": "planned"},
            {"phase": 4, "name": "PWA, Benchmarking & Deploy", "weeks": "10-12", "tasks": 30, "status": "planned"}
        ],
        "current_phase": 1,
        "completion_percentage": 8.5
    }

def _get_architecture_diagram() -> Dict[str, Any]:
    """Return architecture components"""
    return {
        "hosting": {
            "provider": "Render",
            "tier": "8GB RAM / 4 vCPU",
            "features": ["Auto-scaling", "Zero downtime deploys", "SSL/TLS", "Custom domains"]
        },
        "version_control": {
            "provider": "GitHub",
            "features": ["Auto-commit worker", "Branch protection", "Code review via Replit Agent"]
        },
        "ai_reviewer": {
            "name": "Replit Agent",
            "role": "Primary code reviewer and quality assurance"
        },
        "backend": {
            "framework": "FastAPI",
            "language": "Python 3.11",
            "database": "PostgreSQL (Neon)",
            "cache": "Redis (planned)"
        },
        "frontend": {
            "framework": "React + TypeScript",
            "styling": "Tailwind CSS",
            "charts": "Chart.js + Recharts",
            "mobile": "PWA (Progressive Web App)"
        },
        "workers": [
            "Auto Scanner (531 symbols, 60s interval)",
            "GPT-5 Central Brain",
            "Position Monitor",
            "Sentinel Security",
            "Daily Digest",
            "GitHub Auto-Commit",
            "Heartbeat Monitor",
            "N8N Bridge"
        ]
    }

async def _get_live_metrics() -> Dict[str, Any]:
    """Fetch live metrics from database and system"""
    metrics = {
        "timestamp": datetime.utcnow().isoformat(),
        "system": _get_system_uptime(),
        "trades": {
            "total_today": 0,
            "total_week": 0,
            "total_all_time": 0,
            "win_rate": 0.0,
            "total_pnl": 0.0
        },
        "ai_consensus": {
            "average_score": 0.0,
            "total_proposals": 0,
            "approved_count": 0
        },
        "performance": {
            "avg_rr": 0.0,
            "best_trade_pnl": 0.0,
            "worst_trade_pnl": 0.0
        }
    }
    
    with suppress(Exception):
        from utils.storage import load_trades
        from dateutil import parser
        
        trades_all = load_trades()
        
        if trades_all:
            today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
            week_ago_start = today_start - timedelta(days=7)
            
            trades_today = []
            trades_week = []
            
            for t in trades_all:
                if 'created_at' in t or 'timestamp' in t:
                    try:
                        ts_str = t.get('created_at') or t.get('timestamp')
                        if ts_str:
                            trade_date = parser.parse(ts_str) if isinstance(ts_str, str) else datetime.fromtimestamp(ts_str)
                            if trade_date >= today_start:
                                trades_today.append(t)
                            if trade_date >= week_ago_start:
                                trades_week.append(t)
                    except:
                        pass
            
            metrics["trades"]["total_today"] = len(trades_today)
            metrics["trades"]["total_week"] = len(trades_week)
            metrics["trades"]["total_all_time"] = len(trades_all)
            
            pnls = []
            for t in trades_all:
                try:
                    pnl = float(t.get("pnl") or t.get("realized_pnl") or t.get("profit") or 0)
                    if pnl != 0:
                        pnls.append(pnl)
                except:
                    pass
            
            if pnls:
                wins = sum(1 for p in pnls if p > 0)
                metrics["trades"]["win_rate"] = round((wins / len(pnls)) * 100, 2)
                metrics["trades"]["total_pnl"] = round(sum(pnls), 2)
                metrics["performance"]["best_trade_pnl"] = round(max(pnls), 2)
                metrics["performance"]["worst_trade_pnl"] = round(min(pnls), 2)
                
                rrs = [float(t.get("rr") or t.get("risk_reward") or 0) for t in trades_all if t.get("rr") or t.get("risk_reward")]
                if rrs:
                    metrics["performance"]["avg_rr"] = round(sum(rrs) / len(rrs), 2)
    
    return metrics

@router.get("/presentation", summary="בס\"ד - Dynamic Presentation Data")
async def get_presentation_data():
    """
    Returns dynamic presentation data that auto-updates
    
    **Features:**
    - 8 AI models mesh configuration
    - 10 news sources status
    - Live trade metrics
    - ROADMAP progress
    - Budget analysis
    - Architecture diagram
    """
    try:
        metrics = await _get_live_metrics()
        
        data = {
            "header": "בס\"ד - AlgoGPT Ultimate Edition",
            "subtitle": "Production-Grade 24/7 Autonomous Algorithmic Trading Platform",
            "timestamp": datetime.utcnow().isoformat(),
            "sections": {
                "architecture": _get_architecture_diagram(),
                "ai_mesh": {
                    "models": _get_ai_mesh_config(),
                    "total_weight": 100,
                    "consensus_threshold": 60
                },
                "news_sources": {
                    "sources": _get_news_sources(),
                    "total_sources": 10,
                    "active_count": sum(1 for s in _get_news_sources() if s["status"] == "active")
                },
                "benchmarking": {
                    "engines": _get_benchmarking_engines(),
                    "total_engines": 8
                },
                "budget": _get_budget_analysis(),
                "roadmap": _get_roadmap_summary(),
                "metrics": metrics,
                "quick_start": {
                    "steps": [
                        "1. Configure API keys (Binance, OpenAI, Telegram)",
                        "2. Deploy to Render 8GB server",
                        "3. Connect GitHub for auto-commits",
                        "4. Enable Replit Agent for code review",
                        "5. Activate 8-AI mesh consensus",
                        "6. Configure 10 news source integrations",
                        "7. Set up multi-tenant user management",
                        "8. Deploy PWA mobile app",
                        "9. Enable performance fee tracking (20-30% above HWM)",
                        "10. Launch 24/7 autonomous trading"
                    ]
                }
            },
            "languages": {
                "primary": "Hebrew",
                "secondary": "English"
            }
        }
        
        return data
        
    except Exception as e:
        logger.error(f"Error generating presentation data: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")

@router.websocket("/ws/presentation")
async def websocket_presentation(websocket: WebSocket):
    """
    WebSocket endpoint for real-time presentation updates
    Pushes updates every 5 seconds
    """
    await websocket.accept()
    
    try:
        while True:
            metrics = await _get_live_metrics()
            
            update = {
                "type": "metrics_update",
                "timestamp": datetime.utcnow().isoformat(),
                "data": metrics
            }
            
            await websocket.send_json(update)
            
            await asyncio.sleep(5)
            
    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected")
    except Exception as e:
        logger.error(f"WebSocket error: {e}", exc_info=True)
        await websocket.close()

def _get_ai_mesh_detailed() -> List[Dict[str, Any]]:
    """Return detailed 8-AI mesh configuration with roles, strengths, use cases"""
    return [
        {
            "name": "Claude Sonnet 4.5",
            "provider": "Anthropic",
            "weight": 45,
            "role": "Primary Decision Engine",
            "strengths": ["Long context (200K tokens)", "Advanced reasoning", "Code analysis", "Multi-step planning"],
            "use_cases": ["Complex trade analysis", "Risk assessment", "Strategy planning", "Multi-timeframe correlation"],
            "model": "claude-sonnet-4.5",
            "status": "active",
            "icon": "🧠"
        },
        {
            "name": "Perplexity",
            "provider": "Perplexity",
            "weight": 25,
            "role": "Real-time Market Intelligence",
            "strengths": ["Real-time web search", "News aggregation", "Market sentiment", "Event detection"],
            "use_cases": ["Breaking news analysis", "Market event correlation", "Sentiment tracking", "Narrative detection"],
            "model": "sonar-reasoning",
            "status": "active",
            "icon": "🔍"
        },
        {
            "name": "Cohere",
            "provider": "Cohere",
            "weight": 20,
            "role": "Semantic Analysis & Classification",
            "strengths": ["Text embeddings", "Classification", "Semantic search", "Multilingual support"],
            "use_cases": ["News categorization", "Pattern recognition", "Trade clustering", "Anomaly detection"],
            "model": "command-r-plus",
            "status": "planned",
            "icon": "🎯"
        },
        {
            "name": "Mistral",
            "provider": "Mistral",
            "weight": 10,
            "role": "Fast Inference & Validation",
            "strengths": ["High-speed inference", "Efficient reasoning", "Function calling", "JSON mode"],
            "use_cases": ["Quick validation", "Real-time checks", "Fast scoring", "Rapid filtering"],
            "model": "mistral-large-2",
            "status": "planned",
            "icon": "⚡"
        },
        {
            "name": "Groq",
            "provider": "Groq",
            "weight": 0,
            "role": "Ultra-fast Processing",
            "strengths": ["Extreme speed (500+ tokens/s)", "Low latency", "Batch processing", "Cost efficiency"],
            "use_cases": ["Bulk analysis", "Pre-screening", "Quick summaries", "High-throughput filtering"],
            "model": "llama-3.3-70b",
            "status": "planned",
            "icon": "🚀"
        },
        {
            "name": "Gemini",
            "provider": "Google",
            "weight": 0,
            "role": "Multimodal Analysis",
            "strengths": ["Multimodal input", "Chart analysis", "Visual pattern recognition", "Long context"],
            "use_cases": ["Chart interpretation", "Visual signals", "Pattern detection", "Technical analysis"],
            "model": "gemini-2.0-flash",
            "status": "planned",
            "icon": "📊"
        },
        {
            "name": "Voyage AI",
            "provider": "Voyage",
            "weight": 0,
            "role": "Advanced Embeddings",
            "strengths": ["State-of-art embeddings", "Financial domain tuning", "Semantic similarity", "RAG optimization"],
            "use_cases": ["Trade similarity", "Historical matching", "Knowledge retrieval", "Context ranking"],
            "model": "voyage-3",
            "status": "planned",
            "icon": "🧭"
        },
        {
            "name": "AI-X (Grok)",
            "provider": "xAI",
            "weight": 0,
            "role": "Contrarian Analysis",
            "strengths": ["Real-time X/Twitter data", "Contrarian thinking", "Humor detection", "Crowd sentiment"],
            "use_cases": ["Social sentiment", "Contrarian signals", "Crowd analysis", "Hype detection"],
            "model": "grok-2",
            "status": "planned",
            "icon": "🤖"
        }
    ]

def _get_architecture_flow() -> Dict[str, Any]:
    """Return detailed architecture flow with 5 layers"""
    return {
        "layers": [
            {
                "id": 1,
                "name": "Data Layer",
                "description": "Real-time market data ingestion and preprocessing",
                "components": [
                    {"name": "Binance Futures API", "type": "exchange", "status": "active"},
                    {"name": "Market Data Stream", "type": "websocket", "status": "active"},
                    {"name": "News Sources (10)", "type": "aggregator", "status": "partial"},
                    {"name": "TradingView Alerts", "type": "webhook", "status": "active"}
                ],
                "throughput": "531 symbols @ 60s intervals",
                "latency": "< 100ms"
            },
            {
                "id": 2,
                "name": "Processing Layer",
                "description": "Multi-timeframe analysis and signal generation",
                "components": [
                    {"name": "Auto Scanner", "type": "worker", "status": "active"},
                    {"name": "8-AI Mesh", "type": "ai_network", "status": "partial"},
                    {"name": "Market Intelligence", "type": "analyzer", "status": "active"},
                    {"name": "Multi-TF Engine", "type": "processor", "status": "active"}
                ],
                "processing_time": "3-5s per symbol",
                "accuracy": "Multi-model consensus"
            },
            {
                "id": 3,
                "name": "Decision Layer",
                "description": "Consensus-based trade decision making",
                "components": [
                    {"name": "GPT-5 Orchestrator", "type": "brain", "status": "active"},
                    {"name": "Consensus Engine", "type": "aggregator", "status": "active"},
                    {"name": "Risk Manager", "type": "validator", "status": "active"},
                    {"name": "Quality Scorer", "type": "filter", "status": "active"}
                ],
                "threshold": "60% consensus required",
                "filters": "Multi-layer risk checks"
            },
            {
                "id": 4,
                "name": "Execution Layer",
                "description": "Trade execution and position management",
                "components": [
                    {"name": "Trade Manager", "type": "executor", "status": "active"},
                    {"name": "Position Monitor", "type": "tracker", "status": "active"},
                    {"name": "Telegram Approval", "type": "gateway", "status": "active"},
                    {"name": "Smart Stop-Loss", "type": "guardian", "status": "active"}
                ],
                "approval_flow": "Manual Telegram confirmation",
                "execution_speed": "< 500ms"
            },
            {
                "id": 5,
                "name": "Storage Layer",
                "description": "Persistent data storage and performance tracking",
                "components": [
                    {"name": "PostgreSQL (Neon)", "type": "database", "status": "active"},
                    {"name": "Trade History", "type": "ledger", "status": "active"},
                    {"name": "Performance Metrics", "type": "analytics", "status": "active"},
                    {"name": "Redis Cache", "type": "cache", "status": "planned"}
                ],
                "retention": "Unlimited trade history",
                "backup": "Auto-commit to GitHub"
            }
        ]
    }

def _get_roadmap_gantt() -> Dict[str, Any]:
    """Return detailed roadmap with Gantt-style task breakdown"""
    return {
        "phases": [
            {
                "id": 1,
                "name": "Foundation & Logo",
                "start_date": "2025-11-04",
                "end_date": "2025-11-24",
                "weeks": 3,
                "status": "in_progress",
                "progress": 12,
                "tasks": [
                    {"id": "1.1", "name": "8-AI Mesh Setup", "duration": 5, "dependencies": [], "status": "in_progress", "assignee": "AI", "priority": "high"},
                    {"id": "1.2", "name": "Professional Logo Design", "duration": 2, "dependencies": [], "status": "completed", "assignee": "AI", "priority": "high"},
                    {"id": "1.3", "name": "Workbook HTML Structure", "duration": 3, "dependencies": ["1.2"], "status": "in_progress", "assignee": "AI", "priority": "high"},
                    {"id": "1.4", "name": "D3.js Visualizations", "duration": 5, "dependencies": ["1.3"], "status": "pending", "assignee": "AI", "priority": "medium"},
                    {"id": "1.5", "name": "RTL Support & i18n", "duration": 2, "dependencies": ["1.3"], "status": "pending", "assignee": "AI", "priority": "medium"},
                    {"id": "1.6", "name": "Glassmorphism Theme", "duration": 3, "dependencies": ["1.3"], "status": "pending", "assignee": "AI", "priority": "low"},
                    {"id": "1.7", "name": "Responsive Design", "duration": 2, "dependencies": ["1.6"], "status": "pending", "assignee": "AI", "priority": "high"}
                ]
            },
            {
                "id": 2,
                "name": "8-AI Mesh Integration",
                "start_date": "2025-11-25",
                "end_date": "2025-12-15",
                "weeks": 3,
                "status": "planned",
                "progress": 0,
                "tasks": [
                    {"id": "2.1", "name": "Anthropic Claude Integration", "duration": 3, "dependencies": [], "status": "planned", "assignee": "AI", "priority": "high"},
                    {"id": "2.2", "name": "Perplexity API Setup", "duration": 2, "dependencies": [], "status": "planned", "assignee": "AI", "priority": "high"},
                    {"id": "2.3", "name": "Cohere Integration", "duration": 3, "dependencies": [], "status": "planned", "assignee": "AI", "priority": "medium"},
                    {"id": "2.4", "name": "Mistral Large Setup", "duration": 2, "dependencies": [], "status": "planned", "assignee": "AI", "priority": "medium"},
                    {"id": "2.5", "name": "Groq Ultra-fast Processing", "duration": 2, "dependencies": [], "status": "planned", "assignee": "AI", "priority": "low"},
                    {"id": "2.6", "name": "Gemini Multimodal", "duration": 3, "dependencies": [], "status": "planned", "assignee": "AI", "priority": "low"},
                    {"id": "2.7", "name": "Voyage Embeddings", "duration": 2, "dependencies": [], "status": "planned", "assignee": "AI", "priority": "low"},
                    {"id": "2.8", "name": "AI-X Grok Integration", "duration": 2, "dependencies": [], "status": "planned", "assignee": "AI", "priority": "low"},
                    {"id": "2.9", "name": "Consensus Engine", "duration": 5, "dependencies": ["2.1", "2.2", "2.3", "2.4"], "status": "planned", "assignee": "AI", "priority": "high"}
                ]
            },
            {
                "id": 3,
                "name": "News & Multi-Tenant",
                "start_date": "2025-12-16",
                "end_date": "2026-01-05",
                "weeks": 3,
                "status": "planned",
                "progress": 0,
                "tasks": [
                    {"id": "3.1", "name": "CoinDesk API", "duration": 2, "dependencies": [], "status": "planned", "assignee": "AI", "priority": "high"},
                    {"id": "3.2", "name": "Bloomberg Integration", "duration": 3, "dependencies": [], "status": "planned", "assignee": "AI", "priority": "high"},
                    {"id": "3.3", "name": "CoinTelegraph Feed", "duration": 2, "dependencies": [], "status": "planned", "assignee": "AI", "priority": "medium"},
                    {"id": "3.4", "name": "Twitter/X Sentiment", "duration": 3, "dependencies": [], "status": "planned", "assignee": "AI", "priority": "medium"},
                    {"id": "3.5", "name": "Reddit Analysis", "duration": 2, "dependencies": [], "status": "planned", "assignee": "AI", "priority": "low"},
                    {"id": "3.6", "name": "Fear & Greed Index", "duration": 1, "dependencies": [], "status": "planned", "assignee": "AI", "priority": "medium"},
                    {"id": "3.7", "name": "Multi-Tenant Architecture", "duration": 5, "dependencies": [], "status": "planned", "assignee": "AI", "priority": "high"},
                    {"id": "3.8", "name": "User Management System", "duration": 4, "dependencies": ["3.7"], "status": "planned", "assignee": "AI", "priority": "high"}
                ]
            },
            {
                "id": 4,
                "name": "PWA, Benchmarking & Deploy",
                "start_date": "2026-01-06",
                "end_date": "2026-01-26",
                "weeks": 3,
                "status": "planned",
                "progress": 0,
                "tasks": [
                    {"id": "4.1", "name": "PWA Setup & Service Workers", "duration": 3, "dependencies": [], "status": "planned", "assignee": "AI", "priority": "high"},
                    {"id": "4.2", "name": "Mobile-First Optimization", "duration": 2, "dependencies": ["4.1"], "status": "planned", "assignee": "AI", "priority": "high"},
                    {"id": "4.3", "name": "Offline Mode Support", "duration": 2, "dependencies": ["4.1"], "status": "planned", "assignee": "AI", "priority": "medium"},
                    {"id": "4.4", "name": "Freqtrade Benchmarking", "duration": 3, "dependencies": [], "status": "planned", "assignee": "AI", "priority": "medium"},
                    {"id": "4.5", "name": "Backtrader Integration", "duration": 2, "dependencies": [], "status": "planned", "assignee": "AI", "priority": "low"},
                    {"id": "4.6", "name": "Performance Comparison Dashboard", "duration": 3, "dependencies": ["4.4", "4.5"], "status": "planned", "assignee": "AI", "priority": "medium"},
                    {"id": "4.7", "name": "8GB Render Deployment", "duration": 2, "dependencies": [], "status": "planned", "assignee": "AI", "priority": "high"},
                    {"id": "4.8", "name": "Production Security Hardening", "duration": 3, "dependencies": ["4.7"], "status": "planned", "assignee": "AI", "priority": "high"},
                    {"id": "4.9", "name": "Performance Fee Tracking (20-30%)", "duration": 2, "dependencies": ["3.7"], "status": "planned", "assignee": "AI", "priority": "high"}
                ]
            }
        ],
        "total_tasks": 35,
        "completed_tasks": 1,
        "in_progress_tasks": 2,
        "pending_tasks": 32,
        "overall_progress": 3
    }

def _get_trading_strategy_flow() -> Dict[str, Any]:
    """Return detailed trading strategy flow with 7 stages"""
    return {
        "stages": [
            {
                "id": 1,
                "name": "Market Scan",
                "description": "Continuous scanning of 531 Binance Futures symbols",
                "duration": "Every 60s",
                "input": "Binance API + Watchlist",
                "output": "531 symbols with market data",
                "technologies": ["Python asyncio", "Binance WebSocket", "Market Intelligence"],
                "metrics": {"symbols_per_cycle": 531, "cycle_duration": "60s", "data_points_per_symbol": 3}
            },
            {
                "id": 2,
                "name": "Multi-TF Analysis",
                "description": "Parallel analysis across 3 timeframes (15M, 1H, 4H)",
                "duration": "3s",
                "input": "OHLCV data (180 candles per TF)",
                "output": "15M/1H/4H signals with confidence scores",
                "technologies": ["Multi-timeframe engine", "Technical indicators", "Trend detection"],
                "metrics": {"timeframes": 3, "indicators_per_tf": 12, "weighted_scoring": "50%/30%/20%"}
            },
            {
                "id": 3,
                "name": "AI Analysis",
                "description": "8-AI mesh consensus-based trade proposal generation",
                "duration": "5-10s",
                "input": "Market signals + News + Sentiment",
                "output": "Trade proposal with reasoning",
                "technologies": ["Claude 4.5", "Perplexity", "Cohere", "Mistral", "GPT-5 Orchestrator"],
                "metrics": {"ai_models": 8, "consensus_threshold": "60%", "reasoning_depth": "multi-step"}
            },
            {
                "id": 4,
                "name": "Consensus Check",
                "description": "Aggregate AI opinions and validate consensus",
                "duration": "2s",
                "input": "8 AI model outputs",
                "output": "Consensus score (0-100%)",
                "technologies": ["Weighted voting", "Disagreement detection", "Confidence scoring"],
                "metrics": {"pass_threshold": "60%", "veto_enabled": True, "weight_distribution": "45/25/20/10"}
            },
            {
                "id": 5,
                "name": "Risk Check",
                "description": "Multi-layer risk validation and position sizing",
                "duration": "1s",
                "input": "Trade proposal + Portfolio state",
                "output": "Pass/Fail + Risk metrics",
                "technologies": ["Risk rules engine", "Position sizer", "Portfolio manager", "Quality scorer"],
                "metrics": {"risk_checks": 12, "max_position_size": "dynamic", "quality_threshold": "4.2/10"}
            },
            {
                "id": 6,
                "name": "Telegram Approval",
                "description": "Human-in-the-loop manual confirmation via Telegram",
                "duration": "Manual (user-dependent)",
                "input": "Trade summary with charts + reasoning",
                "output": "Approve/Reject/Modify",
                "technologies": ["Telegram Bot API", "Interactive buttons", "Chart generation"],
                "metrics": {"approval_required": True, "timeout": "30min", "auto_reject_after": "timeout"}
            },
            {
                "id": 7,
                "name": "Execution",
                "description": "Order placement and position tracking on Binance",
                "duration": "0.5s",
                "input": "Approved trade details",
                "output": "Order placed + Position opened",
                "technologies": ["Binance API", "Order manager", "Position tracker", "Smart stop-loss"],
                "metrics": {"execution_speed": "< 500ms", "slippage_tolerance": "0.1%", "retry_logic": "3 attempts"}
            }
        ],
        "total_duration": "70-80s (excluding manual approval)",
        "automation_level": "Semi-autonomous (requires Telegram approval)",
        "throughput": "Up to 10 trades per hour (filtered by quality)",
        "success_metrics": {
            "win_rate_target": ">= 47%",
            "risk_reward_min": "1.5:1",
            "quality_score_min": "4.2/10"
        }
    }

def _get_news_pipeline() -> List[Dict[str, Any]]:
    """Return detailed news pipeline with 10 sources"""
    return [
        {
            "id": 1,
            "source": "TradingView",
            "category": "technical_alerts",
            "priority": "high",
            "status": "active",
            "processing": "Webhook -> Alert parser -> Trade signals",
            "update_frequency": "Real-time",
            "integration": "Webhook + HMAC verification",
            "use_case": "Technical breakout detection"
        },
        {
            "id": 2,
            "source": "N8N Workflows",
            "category": "automation",
            "priority": "high",
            "status": "active",
            "processing": "Workflow triggers -> Event bridge -> Action execution",
            "update_frequency": "Event-driven",
            "integration": "REST API + Worker bridge",
            "use_case": "Complex automation orchestration"
        },
        {
            "id": 3,
            "source": "Telegram Bot",
            "category": "communication",
            "priority": "high",
            "status": "active",
            "processing": "Bot commands -> User intent -> System actions",
            "update_frequency": "Real-time",
            "integration": "Telegram Bot API + Webhook",
            "use_case": "User interaction and approvals"
        },
        {
            "id": 4,
            "source": "CoinDesk",
            "category": "crypto_news",
            "priority": "high",
            "status": "planned",
            "processing": "RSS feed -> NLP extraction -> Sentiment analysis -> Event detection",
            "update_frequency": "Every 5 minutes",
            "integration": "RSS API + Web scraping",
            "use_case": "Breaking crypto news impact analysis"
        },
        {
            "id": 5,
            "source": "Bloomberg",
            "category": "financial_news",
            "priority": "high",
            "status": "planned",
            "processing": "Terminal API -> News filtering -> Macro event detection -> Asset correlation",
            "update_frequency": "Real-time",
            "integration": "Bloomberg Terminal API (paid)",
            "use_case": "Macro economic events affecting crypto"
        },
        {
            "id": 6,
            "source": "CoinTelegraph",
            "category": "crypto_news",
            "priority": "medium",
            "status": "planned",
            "processing": "RSS + Web scraping -> Article parsing -> Sentiment scoring",
            "update_frequency": "Every 10 minutes",
            "integration": "RSS + BeautifulSoup",
            "use_case": "Crypto industry news and trends"
        },
        {
            "id": 7,
            "source": "Twitter/X",
            "category": "social_sentiment",
            "priority": "medium",
            "status": "planned",
            "processing": "Twitter API v2 -> Crypto influencer tracking -> Sentiment analysis -> Hype detection",
            "update_frequency": "Every 2 minutes",
            "integration": "Twitter API v2 + Grok AI",
            "use_case": "Social sentiment and viral narratives"
        },
        {
            "id": 8,
            "source": "Reddit",
            "category": "community_sentiment",
            "priority": "medium",
            "status": "planned",
            "processing": "Reddit API -> Subreddit monitoring -> Upvote analysis -> Trend detection",
            "update_frequency": "Every 5 minutes",
            "integration": "Reddit API (PRAW)",
            "use_case": "Community sentiment on r/cryptocurrency, r/bitcoin"
        },
        {
            "id": 9,
            "source": "Binance Announcements",
            "category": "exchange_updates",
            "priority": "high",
            "status": "planned",
            "processing": "Official RSS -> Listing detection -> Delisting warnings -> Policy changes",
            "update_frequency": "Real-time",
            "integration": "RSS + Websocket notifications",
            "use_case": "New coin listings, delisting warnings"
        },
        {
            "id": 10,
            "source": "Fear & Greed Index",
            "category": "market_sentiment",
            "priority": "medium",
            "status": "planned",
            "processing": "Alternative.me API -> Index calculation -> Regime detection -> Strategy adjustment",
            "update_frequency": "Every 1 hour",
            "integration": "REST API (free)",
            "use_case": "Market regime detection (extreme fear/greed)"
        }
    ]

@router.get("/workbook", summary="בס\"ד - Professional Workbook Data")
async def get_workbook_data():
    """
    Returns comprehensive workbook data for AlgoGPT Ultimate Edition
    
    **Includes:**
    - Professional logo path
    - Detailed 8-AI mesh with roles, strengths, use cases
    - 5-layer architecture flow diagram
    - Gantt-style roadmap with 35 detailed tasks
    - 7-stage trading strategy flow
    - 10-source news pipeline configuration
    """
    try:
        data = {
            "logo_path": "/static/dashboard/algogpt-logo.svg",
            "ai_mesh_detailed": _get_ai_mesh_detailed(),
            "architecture_flow": _get_architecture_flow(),
            "roadmap_gantt": _get_roadmap_gantt(),
            "trading_strategy_flow": _get_trading_strategy_flow(),
            "news_pipeline": _get_news_pipeline(),
            "metadata": {
                "version": "1.0.0",
                "generated_at": datetime.utcnow().isoformat(),
                "phase": "1 - Foundation & Logo",
                "completion": "12%",
                "next_milestone": "D3.js Visualizations"
            }
        }
        
        return data
        
    except Exception as e:
        logger.error(f"Error generating workbook data: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")










