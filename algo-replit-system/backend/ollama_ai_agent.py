"""
ALGO-REPLIT Ollama AI Agent Integration
Code generation, modification, error explanation, project scaffolding
"""

import os
import json
import httpx
import logging
from typing import Optional, Dict, Any, List
from pydantic import BaseModel
import difflib

logger = logging.getLogger(__name__)

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama2")

class CodeGenRequest(BaseModel):
    prompt: str
    context: Optional[str] = None
    language: str = "python"

class CodeModifyRequest(BaseModel):
    code: str
    instruction: str
    language: str = "python"

class ErrorExplainRequest(BaseModel):
    error_message: str
    code_context: Optional[str] = None

class OllamaAIAgent:
    def __init__(self):
        self.base_url = OLLAMA_BASE_URL
        self.model = OLLAMA_MODEL
        self.client = httpx.AsyncClient(timeout=120.0)
    
    async def check_availability(self) -> bool:
        """Check if Ollama is available"""
        try:
            response = await self.client.get(f"{self.base_url}/api/tags")
            return response.status_code == 200
        except Exception as e:
            logger.warning(f"Ollama unavailable: {e}")
            return False
    
    async def generate_code(self, req: CodeGenRequest) -> Dict[str, Any]:
        """Generate code using Ollama"""
        prompt = f"""
        You are an expert {req.language} developer.
        Generate clean, production-ready code for the following:
        
        {req.prompt}
        
        {f'Context: {req.context}' if req.context else ''}
        
        Provide only the code, no explanations.
        """
        
        try:
            response = await self.client.post(
                f"{self.base_url}/api/generate",
                json={
                    "model": self.model,
                    "prompt": prompt,
                    "stream": False,
                    "temperature": 0.3,
                }
            )
            
            result = response.json()
            return {
                "status": "success",
                "code": result.get("response", ""),
                "model": self.model,
            }
        except Exception as e:
            logger.error(f"Code generation failed: {e}")
            return {"status": "error", "message": str(e)}
    
    async def modify_code(self, req: CodeModifyRequest) -> Dict[str, Any]:
        """Modify existing code with instructions"""
        prompt = f"""
        You are an expert {req.language} developer.
        Modify the following code according to the instruction:
        
        INSTRUCTION: {req.instruction}
        
        ORIGINAL CODE:
        ```{req.language}
        {req.code}
        ```
        
        Provide the MODIFIED code only, no explanations.
        Keep the same structure and style as the original.
        """
        
        try:
            response = await self.client.post(
                f"{self.base_url}/api/generate",
                json={
                    "model": self.model,
                    "prompt": prompt,
                    "stream": False,
                    "temperature": 0.2,
                }
            )
            
            result = response.json()
            modified_code = result.get("response", "")
            
            # Generate diff
            diff = list(difflib.unified_diff(
                req.code.splitlines(keepends=True),
                modified_code.splitlines(keepends=True),
                fromfile="original",
                tofile="modified",
                lineterm=""
            ))
            
            return {
                "status": "success",
                "modified_code": modified_code,
                "diff": "".join(diff),
                "model": self.model,
            }
        except Exception as e:
            logger.error(f"Code modification failed: {e}")
            return {"status": "error", "message": str(e)}
    
    async def explain_error(self, req: ErrorExplainRequest) -> Dict[str, Any]:
        """Explain error message and suggest fixes"""
        prompt = f"""
        You are an expert debugger.
        Explain the following error and suggest fixes:
        
        ERROR MESSAGE:
        {req.error_message}
        
        {f'CODE CONTEXT:\\n```\\n{req.code_context}\\n```' if req.code_context else ''}
        
        Provide:
        1. What the error means
        2. Why it occurs
        3. How to fix it
        4. Prevention tips
        """
        
        try:
            response = await self.client.post(
                f"{self.base_url}/api/generate",
                json={
                    "model": self.model,
                    "prompt": prompt,
                    "stream": False,
                    "temperature": 0.5,
                }
            )
            
            result = response.json()
            return {
                "status": "success",
                "explanation": result.get("response", ""),
                "model": self.model,
            }
        except Exception as e:
            logger.error(f"Error explanation failed: {e}")
            return {"status": "error", "message": str(e)}
    
    async def scaffold_project(self, language: str, project_type: str) -> Dict[str, Any]:
        """Generate project scaffolding"""
        prompt = f"""
        Generate a complete {project_type} project structure in {language}.
        Include:
        - Directory structure
        - Main entry file
        - Requirements/dependencies
        - Basic configuration
        - Sample code
        
        Format as JSON with keys: directories, files (with content)
        """
        
        try:
            response = await self.client.post(
                f"{self.base_url}/api/generate",
                json={
                    "model": self.model,
                    "prompt": prompt,
                    "stream": False,
                    "temperature": 0.4,
                }
            )
            
            result = response.json()
            return {
                "status": "success",
                "scaffold": result.get("response", ""),
                "model": self.model,
            }
        except Exception as e:
            logger.error(f"Project scaffolding failed: {e}")
            return {"status": "error", "message": str(e)}
    
    async def chat(self, message: str, context: Optional[List[Dict]] = None) -> Dict[str, Any]:
        """Chat interface with context history"""
        messages = context or []
        messages.append({"role": "user", "content": message})
        
        # Format messages for Ollama
        formatted_messages = "\n".join([
            f"{msg['role'].upper()}: {msg['content']}"
            for msg in messages
        ])
        
        prompt = f"""
        {formatted_messages}
        
        ASSISTANT:
        """
        
        try:
            response = await self.client.post(
                f"{self.base_url}/api/generate",
                json={
                    "model": self.model,
                    "prompt": prompt,
                    "stream": False,
                    "temperature": 0.7,
                }
            )
            
            result = response.json()
            assistant_message = result.get("response", "").strip()
            
            return {
                "status": "success",
                "message": assistant_message,
                "model": self.model,
            }
        except Exception as e:
            logger.error(f"Chat failed: {e}")
            return {"status": "error", "message": str(e)}

# Singleton instance
ollama_agent = OllamaAIAgent()

async def get_ollama_agent() -> OllamaAIAgent:
    """Dependency: get Ollama agent"""
    return ollama_agent
