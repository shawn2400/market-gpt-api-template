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










