"""
Render.com API Integration
Manages Render services programmatically
"""

import os
import httpx
import asyncio
from typing import Dict, List, Optional
import logging

logger = logging.getLogger(__name__)

class RenderAPI:
    """Render.com API Client"""
    
    BASE_URL = "https://api.render.com/v1"
    
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("RENDER_API_KEY")
        if not self.api_key:
            raise ValueError("RENDER_API_KEY not found in environment")
        
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
    
    async def list_services(self) -> List[Dict]:
        """List all Render services"""
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.BASE_URL}/services",
                headers=self.headers,
                timeout=30.0
            )
            response.raise_for_status()
            return response.json()
    
    async def get_service(self, service_id: str) -> Dict:
        """Get service details"""
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.BASE_URL}/services/{service_id}",
                headers=self.headers,
                timeout=30.0
            )
            response.raise_for_status()
            return response.json()
    
    async def create_web_service(
        self,
        name: str,
        repo_url: str,
        branch: str = "main",
        build_command: str = "pip install -r requirements.txt",
        start_command: str = "gunicorn main:app",
        env_vars: Optional[List[Dict]] = None,
        plan: str = "standard",  # starter, standard, pro
        region: str = "singapore"
    ) -> Dict:
        """Create a new web service"""
        payload = {
            "type": "web_service",
            "name": name,
            "ownerId": await self._get_owner_id(),
            "repo": repo_url,
            "branch": branch,
            "buildFilter": {
                "paths": [],
                "ignoredPaths": []
            },
            "envSpecificDetails": {
                "buildCommand": build_command,
                "startCommand": start_command,
                "plan": plan,
                "region": region,
                "pullRequestPreviewsEnabled": "no"
            }
        }
        
        if env_vars:
            payload["envVars"] = env_vars
        
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.BASE_URL}/services",
                headers=self.headers,
                json=payload,
                timeout=60.0
            )
            response.raise_for_status()
            return response.json()
    
    async def create_background_worker(
        self,
        name: str,
        repo_url: str,
        branch: str = "main",
        build_command: str = "pip install -r requirements.txt",
        start_command: str = "python worker.py",
        env_vars: Optional[List[Dict]] = None,
        plan: str = "starter",
        region: str = "singapore"
    ) -> Dict:
        """Create a new background worker"""
        payload = {
            "type": "background_worker",
            "name": name,
            "ownerId": await self._get_owner_id(),
            "repo": repo_url,
            "branch": branch,
            "buildFilter": {
                "paths": [],
                "ignoredPaths": []
            },
            "envSpecificDetails": {
                "buildCommand": build_command,
                "startCommand": start_command,
                "plan": plan,
                "region": region
            }
        }
        
        if env_vars:
            payload["envVars"] = env_vars
        
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.BASE_URL}/services",
                headers=self.headers,
                json=payload,
                timeout=60.0
            )
            response.raise_for_status()
            return response.json()
    
    async def create_postgres_database(
        self,
        name: str,
        database_name: str,
        user: str,
        plan: str = "starter",  # free, starter
        region: str = "singapore"
    ) -> Dict:
        """Create a PostgreSQL database"""
        payload = {
            "name": name,
            "ownerId": await self._get_owner_id(),
            "databaseName": database_name,
            "databaseUser": user,
            "plan": plan,
            "region": region
        }
        
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.BASE_URL}/postgres",
                headers=self.headers,
                json=payload,
                timeout=60.0
            )
            response.raise_for_status()
            return response.json()
    
    async def update_env_vars(
        self,
        service_id: str,
        env_vars: List[Dict]
    ) -> Dict:
        """Update environment variables for a service"""
        async with httpx.AsyncClient() as client:
            response = await client.put(
                f"{self.BASE_URL}/services/{service_id}/env-vars",
                headers=self.headers,
                json=env_vars,
                timeout=60.0
            )
            response.raise_for_status()
            return response.json()
    
    async def trigger_deploy(self, service_id: str) -> Dict:
        """Trigger a manual deployment"""
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.BASE_URL}/services/{service_id}/deploys",
                headers=self.headers,
                json={"clearCache": "do_not_clear"},
                timeout=60.0
            )
            response.raise_for_status()
            return response.json()
    
    async def get_deploy_status(self, service_id: str, deploy_id: str) -> Dict:
        """Get deployment status"""
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.BASE_URL}/services/{service_id}/deploys/{deploy_id}",
                headers=self.headers,
                timeout=30.0
            )
            response.raise_for_status()
            return response.json()
    
    async def delete_service(self, service_id: str) -> bool:
        """Delete a service"""
        async with httpx.AsyncClient() as client:
            response = await client.delete(
                f"{self.BASE_URL}/services/{service_id}",
                headers=self.headers,
                timeout=30.0
            )
            response.raise_for_status()
            return True
    
    async def _get_owner_id(self) -> str:
        """Get the owner ID for the authenticated user"""
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.BASE_URL}/owners",
                headers=self.headers,
                timeout=30.0
            )
            response.raise_for_status()
            data = response.json()
            if data and len(data) > 0:
                return data[0]["owner"]["id"]
            raise ValueError("No owner found for this API key")


async def main():
    """Test the Render API"""
    render = RenderAPI()
    
    print("🔍 Fetching Render services...")
    services = await render.list_services()
    print(f"✅ Found {len(services)} services")
    
    for service in services:
        svc = service.get("service", {})
        print(f"  - {svc.get('name')} ({svc.get('type')}) - {svc.get('serviceDetails', {}).get('url', 'N/A')}")


if __name__ == "__main__":
    asyncio.run(main())
