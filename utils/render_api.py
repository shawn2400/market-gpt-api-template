# FILE: utils/render_api.py
from __future__ import annotations
import aiohttp
from typing import Any, Dict, Optional, Tuple

class RenderAPI:
    def __init__(self, api_key: str, base: str = "https://api.render.com"):
        self.base = base.rstrip("/")
        self.headers = {
            "Authorization": f"Bearer {api_key.strip()}",
            "Content-Type": "application/json",
        }
        self.timeout = aiohttp.ClientTimeout(total=15)

    async def _req(self, method: str, path: str, json_body: Optional[Dict[str, Any]] = None) -> Tuple[int, Dict[str, Any]]:
        url = f"{self.base}{path}"
        async with aiohttp.ClientSession(timeout=self.timeout, headers=self.headers) as s:
            async with s.request(method.upper(), url, json=json_body) as r:
                try:
                    data = await r.json()
                except Exception:
                    data = {"text": await r.text()}
                return r.status, data

    async def get_service(self, service_id: str) -> Dict[str, Any]:
        status, data = await self._req("GET", f"/v1/services/{service_id}")
        data["_http_status"] = status
        return data

    async def create_deploy(self, service_id: str) -> bool:
        status, _ = await self._req("POST", f"/v1/services/{service_id}/deploys", json_body={})
        return 200 <= status < 300

    async def set_env_var_compat(self, service_id: str, key: str, value: str, visibility: str = "private") -> bool:
        """
        מנסה כמה פורמטים נפוצים של Render API לעדכון ENV.
        """
        # ניסיון 1: PUT envVars (bulk)
        body_a = {"envVars": [{"key": key, "value": value, "visibility": visibility}]}
        sa, _ = await self._req("PUT", f"/v1/services/{service_id}/env-vars", json_body=body_a)
        if 200 <= sa < 300:
            return True

        # ניסיון 2: POST single
        body_b = {"key": key, "value": value, "visibility": visibility}
        sb, _ = await self._req("POST", f"/v1/services/{service_id}/env-vars", json_body=body_b)
        if 200 <= sb < 300:
            return True

        # ניסיון 3: PUT עם type SECRET/GENERAL
        body_c = {"envVars": [{"key": key, "value": value, "type": "SECRET" if visibility == "private" else "GENERAL"}]}
        sc, _ = await self._req("PUT", f"/v1/services/{service_id}/env-vars", json_body=body_c)
        return 200 <= sc < 300

