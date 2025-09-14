# FILE: utils/render_api.py
from __future__ import annotations
import aiohttp
from typing import Any, Dict, Optional

class RenderAPI:
    def __init__(self, api_key: str, base: str = "https://api.render.com"):
        self.base = base.rstrip("/")
        self.headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

    async def _req(self, method: str, path: str, json_body: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        url = f"{self.base}{path}"
        timeout = aiohttp.ClientTimeout(total=15)
        async with aiohttp.ClientSession(timeout=timeout, headers=self.headers) as s:
            async with s.request(method.upper(), url, json=json_body) as r:
                try:
                    data = await r.json()
                except Exception:
                    data = {"status": r.status, "text": await r.text()}
                data["_http_status"] = r.status
                return data

    async def get_service(self, service_id: str) -> Dict[str, Any]:
        return await self._req("GET", f"/v1/services/{service_id}")

    async def create_deploy(self, service_id: str) -> bool:
        # Render: POST /v1/services/{serviceId}/deploys
        data = await self._req("POST", f"/v1/services/{service_id}/deploys", json_body={})
        return 200 <= data.get("_http_status", 0) < 300

    async def set_env_var_compat(self, service_id: str, key: str, value: str, visibility: str = "private") -> bool:
        """
        מנסה כמה פורמטים נפוצים של Render API לעדכון ENV.
        אם ה־API בארגון שלך שונה—נחזור False (וה־Supervisor רק יתריע, לא ייפול).
        """
        # ניסיון 1: PUT envVars (פורמט A)
        body_a = {"envVars": [{"key": key, "value": value, "visibility": visibility}]}
        a = await self._req("PUT", f"/v1/services/{service_id}/env-vars", json_body=body_a)
        if 200 <= a.get("_http_status", 0) < 300:
            return True
        # ניסיון 2: POST envVars (פורמט B)
        body_b = {"key": key, "value": value, "visibility": visibility}
        b = await self._req("POST", f"/v1/services/{service_id}/env-vars", json_body=body_b)
        if 200 <= b.get("_http_status", 0) < 300:
            return True
        # ניסיון 3: חלק מהממשקים משתמשים ב-type=SECRET/GENERAL
        body_c = {"envVars": [{"key": key, "value": value, "type": "SECRET" if visibility=="private" else "GENERAL"}]}
        c = await self._req("PUT", f"/v1/services/{service_id}/env-vars", json_body=body_c)
        return 200 <= c.get("_http_status", 0) < 300
