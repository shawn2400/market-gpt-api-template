#!/usr/bin/env python3
"""
News Sentiment Analyzer Worker
Analyzes crypto news headlines and market sentiment using AI
Feeds sentiment data into trading decisions
"""
import os
import sys
import time
import asyncio
import logging
import httpx
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.alerts import send_telegram_message

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("news_sentiment")

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-5-2025-08-07").strip()
NEWS_INTERVAL_SEC = int(os.getenv("NEWS_SENTIMENT_INTERVAL", "3600"))
NEWS_ENABLED = os.getenv("NEWS_SENTIMENT_ENABLED", "1").lower() in ("1", "true", "yes")

# News API configuration (using free CryptoPanic-style API)
NEWS_API_URL = os.getenv("NEWS_API_URL", "https://cryptopanic.com/api/v1/posts/")
NEWS_API_KEY = os.getenv("NEWS_API_KEY", "").strip()  # Optional: get from cryptopanic.com

_openai_client: Optional[httpx.AsyncClient] = None

def init_openai_client():
    """Initialize OpenAI HTTP client for sentiment analysis"""
    global _openai_client
    
    if not OPENAI_API_KEY:
        logger.warning("OPENAI_API_KEY not set - sentiment analysis disabled")
        return None
    
    try:
        _openai_client = httpx.AsyncClient(
            base_url="https://api.openai.com/v1",
            headers={
                "Authorization": f"Bearer {OPENAI_API_KEY}",
                "Content-Type": "application/json"
            },
            timeout=60.0
        )
        logger.info(f"News sentiment analyzer initialized with model: {OPENAI_MODEL}")
        return _openai_client
    except Exception as e:
        logger.error(f"Failed to initialize OpenAI client: {e}")
        return None

async def fetch_crypto_news() -> List[Dict[str, Any]]:
    """
    Fetch latest crypto news headlines
    
    Returns:
        List of news items with title, source, time
    """
    try:
        # Mock news for now (in production, use real news API)
        # You can integrate with CryptoPanic, NewsAPI, or crypto RSS feeds
        
        mock_news = [
            {
                "title": "Bitcoin breaks $70,000 resistance level",
                "source": "CoinDesk",
                "published": datetime.now().isoformat(),
                "url": "#"
            },
            {
                "title": "Ethereum upgrade scheduled for next month",
                "source": "The Block",
                "published": datetime.now().isoformat(),
                "url": "#"
            },
            {
                "title": "Major exchange reports record trading volume",
                "source": "Decrypt",
                "published": datetime.now().isoformat(),
                "url": "#"
            }
        ]
        
        logger.info(f"Fetched {len(mock_news)} news items")
        return mock_news
        
    except Exception as e:
        logger.error(f"Failed to fetch news: {e}")
        return []

async def analyze_sentiment(headlines: List[str]) -> Optional[Dict[str, Any]]:
    """
    Analyze sentiment of news headlines using GPT-5
    
    Args:
        headlines: List of news headlines
        
    Returns:
        Sentiment analysis with score and breakdown
    """
    if not _openai_client:
        return None
    
    try:
        headlines_text = "\n".join(f"- {h}" for h in headlines)
        
        prompt = f"""Analyze the sentiment of these crypto news headlines:

{headlines_text}

Provide JSON response with sentiment analysis:
{{
  "overall_sentiment": "BULLISH|NEUTRAL|BEARISH",
  "sentiment_score": <-100 to +100>,
  "confidence": <0-100>,
  "bullish_signals": <count>,
  "bearish_signals": <count>,
  "key_themes": ["theme1", "theme2"],
  "market_impact": "HIGH|MEDIUM|LOW",
  "summary": "<brief analysis>"
}}"""

        messages = [
            {
                "role": "system",
                "content": "You are a crypto market sentiment analyst. Return ONLY valid JSON."
            },
            {
                "role": "user",
                "content": prompt
            }
        ]
        
        response = await _openai_client.post(
            "/chat/completions",
            json={
                "model": OPENAI_MODEL,
                "messages": messages,
                "temperature": 0.2,
                "max_tokens": 600
            }
        )
        
        response.raise_for_status()
        data = response.json()
        
        content = data["choices"][0]["message"]["content"].strip()
        
        # Parse JSON response
        import json
        result = json.loads(content)
        
        logger.info(f"Sentiment: {result.get('overall_sentiment')} (score={result.get('sentiment_score')})")
        return result
        
    except Exception as e:
        logger.error(f"Sentiment analysis failed: {e}")
        return None

async def store_sentiment(sentiment: Dict[str, Any]):
    """
    Store sentiment data for trading decisions
    
    In production, save to database or cache for retrieval by trading system
    """
    try:
        # Save to file for now (in production, use database)
        sentiment_file = "/tmp/latest_sentiment.json"
        
        import json
        with open(sentiment_file, 'w') as f:
            json.dump({
                "timestamp": datetime.now().isoformat(),
                "sentiment": sentiment
            }, f, indent=2)
        
        logger.info(f"Sentiment stored: {sentiment.get('overall_sentiment')}")
        
    except Exception as e:
        logger.error(f"Failed to store sentiment: {e}")

async def run_sentiment_cycle():
    """Run sentiment analysis cycle"""
    try:
        logger.info("Running news sentiment analysis cycle...")
        
        # Fetch news
        news_items = await fetch_crypto_news()
        
        if not news_items:
            logger.warning("No news items fetched")
            return
        
        # Extract headlines
        headlines = [item["title"] for item in news_items[:10]]  # Analyze top 10
        
        # Analyze sentiment
        sentiment = await analyze_sentiment(headlines)
        
        if sentiment:
            # Store for trading system
            await store_sentiment(sentiment)
            
            # Send alert if strong sentiment
            impact = sentiment.get("market_impact", "LOW")
            if impact in ("HIGH", "MEDIUM"):
                await send_sentiment_alert(sentiment, news_items[:3])
        
        logger.info("Sentiment analysis cycle completed")
        
    except Exception as e:
        logger.error(f"Sentiment cycle error: {e}")

async def send_sentiment_alert(sentiment: Dict[str, Any], top_news: List[Dict[str, Any]]):
    """Send sentiment alert to Telegram"""
    try:
        overall = sentiment.get("overall_sentiment", "NEUTRAL")
        score = sentiment.get("sentiment_score", 0)
        confidence = sentiment.get("confidence", 0)
        
        emoji = "🚀" if overall == "BULLISH" else "📉" if overall == "BEARISH" else "📊"
        
        news_text = "\n".join(f"• {item['title']}" for item in top_news)
        
        msg = f"""{emoji} <b>News Sentiment Alert</b>

⏰ <b>Time:</b> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
📰 <b>Sentiment:</b> {overall}
📊 <b>Score:</b> {score:+d}/100
🎯 <b>Confidence:</b> {confidence}%
⚠️ <b>Market Impact:</b> {sentiment.get('market_impact')}

<b>Top Headlines:</b>
{news_text}

<b>Analysis:</b> {sentiment.get('summary', 'N/A')}"""

        await send_telegram_message(msg)
        logger.info(f"Sentiment alert sent: {overall}")
        
    except Exception as e:
        logger.warning(f"Failed to send sentiment alert: {e}")

async def send_startup_notification():
    """Send startup notification"""
    try:
        msg = f"""📰 <b>News Sentiment Analyzer Started</b>

⏰ <b>Time:</b> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
🤖 <b>Model:</b> {OPENAI_MODEL}
✅ <b>Status:</b> Active
🔍 <b>Analyzing crypto news sentiment</b>

The analyzer monitors news headlines and provides market sentiment insights for better trading decisions."""

        await send_telegram_message(msg)
        logger.info("Startup notification sent to Telegram")
        
    except Exception as e:
        logger.warning(f"Failed to send startup notification: {e}")

async def main():
    """Main worker loop"""
    if not NEWS_ENABLED:
        logger.info("News Sentiment Analyzer is disabled (NEWS_SENTIMENT_ENABLED=0)")
        return
    
    logger.info(f"News Sentiment Analyzer started (interval: {NEWS_INTERVAL_SEC}s)")
    
    client = init_openai_client()
    if not client:
        logger.error("OpenAI client initialization failed - exiting")
        return
    
    # Send startup notification
    await send_startup_notification()
    
    while True:
        try:
            await run_sentiment_cycle()
            
            # Sleep until next cycle
            logger.info(f"Sleeping for {NEWS_INTERVAL_SEC} seconds...")
            await asyncio.sleep(NEWS_INTERVAL_SEC)
            
        except KeyboardInterrupt:
            logger.info("News Sentiment Analyzer stopped by user")
            break
        except Exception as e:
            logger.error(f"Unexpected error in sentiment loop: {e}")
            await asyncio.sleep(60)  # Short sleep on error

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("News Sentiment Analyzer shutdown")
