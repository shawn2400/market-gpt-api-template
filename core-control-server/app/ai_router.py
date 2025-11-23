"""AI Engine - Local Ollama + Remote Fallback"""

import requests
import os
from typing import Optional

class OllamaClient:
    def __init__(self, host: str = "http://localhost:11434"):
        self.host = host
    
    def generate(self, prompt: str, model: str = "llama2") -> Optional[str]:
        """Generate text using Ollama"""
        try:
            response = requests.post(
                f"{self.host}/api/generate",
                json={
                    "model": model,
                    "prompt": prompt,
                    "stream": False
                },
                timeout=20
            )
            return response.json().get("response", "")
        except Exception as e:
            return None

class GPTFallback:
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
    
    def generate(self, prompt: str) -> Optional[str]:
        """Generate text using OpenAI (fallback)"""
        if not self.api_key:
            return None
        
        try:
            from openai import OpenAI
            client = OpenAI(api_key=self.api_key)
            
            response = client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[{"role": "user", "content": prompt}],
                timeout=20
            )
            return response.choices[0].message.content
        except Exception:
            return None

class AIRouter:
    def __init__(self):
        self.local = OllamaClient()
        self.remote = GPTFallback()
    
    def ask(self, prompt: str) -> str:
        """Ask AI question - tries local first, fallback to remote"""
        # Try local Ollama first
        response = self.local.generate(prompt)
        if response:
            return response
        
        # Fallback to remote
        response = self.remote.generate(prompt)
        if response:
            return response
        
        # Default if both fail
        return "AI service unavailable"
