# FILE: utils/render_api.py
from __future__ import annotations
import aiohttp
from typing import Any, Dict, List, Optional

RENDER_API_BASE = "https://api.render.com"

class RenderAPI:
    """
    דק-קליינט ל-Render API עם כמה נתיבים נפוצים:
    - list_services
    - get_service
    - create_deploy
    - set_env_var_compat (ניסיון תאימות בכמה שיטות)
    """
    def __init__(self, api_key: str, api_base: str = RENDER_API_BASE):
        self.api_key = api_key
        self.api_base = api_base.rstrip("/")

    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    async def _get(self, session: aiohttp.ClientSession, path: str) -> Any:
        url = f"{self.api_base}{path}"
        async with session.get(url, headers=self._headers()) as resp:
            resp.raise_for_status()
            return await resp.json()

    async def _post(self, session: aiohttp.ClientSession, path: str, json_body: Any = None) -> Any:
        url = f"{self.api_base}{path}"
        async with session.post(url, headers=self._headers(), json=json_body) as resp:
            if resp.status // 100 != 2:
                text = await resp.text()
                raise RuntimeError(f"POST {path} failed: {resp.status} {text}")
            if resp.content_type and "application/json" in resp.content_type:
                return await resp.json()
            return await resp.text()

    async def _patch(self, session: aiohttp.ClientSession, path: str, json_body: Any = None) -> Any:
        url = f"{self.api_base}{path}"
        async with session.patch(url, headers=self._headers(), json=json_body) as resp:
            if resp.status // 100 != 2:
                text = await resp.text()
                raise RuntimeError(f"PATCH {path} failed: {resp.status} {text}")
            if resp.content_type and "application/json" in resp.content_type:
                return await resp.json()
            return await resp.text()

    async def _put(self, session: aiohttp.ClientSession, path: str, json_body: Any = None) -> Any:
        url = f"{self.api_base}{path}"
        async with session.put(url, headers=self._headers(), json=json_body) as resp:
            if resp.status // 100 != 2:
                text = await resp.text()
                raise RuntimeError(f"PUT {path} failed: {resp.status} {text}")
            if resp.content_type and "application/json" in resp.content_type:
                return await resp.json()
            return await resp.text()

    # ---------- Services ----------
    async def list_services(self) -> List[Dict[str, Any]]:
        async with aiohttp.ClientSession() as s:
            # Render מחזיר לעיתים רשימה של אובייקטים עם {cursor, service:{...}}
            data = await self._get(s, "/v1/services")
            return data

    async def get_service(self, service_id: str) -> Dict[str, Any]:
        async with aiohttp.ClientSession() as s:
            return await self._get(s, f"/v1/services/{service_id}")

    async def create_deploy(self, service_id: str) -> Any:
        """
        טריגר דיפלוי לשירות נתון.
        """
        async with aiohttp.ClientSession() as s:
            return await self._post(s, f"/v1/services/{service_id}/deploys", json_body={})

    # ---------- Env Vars (compat) ----------
    async def set_env_var_compat(self, service_id: str, key: str, value: str, visibility: str = "private") -> bool:
        """
        מנסה לעדכן/ליצור משתנה סביבה בכמה וריאציות אפשריות, כדי להיות סובלני לשינויים ב-API.
        מחזיר True אם אחד מהם הצליח (2xx).
        פורמט סטנדרטי: רשימה של אובייקטים {key, value, visibility}
        """
        payload_list = [{"key": key, "value": value, "visibility": visibility}]
        paths = [
            ("POST", f"/v1/services/{service_id}/env-vars"),
            ("PATCH", f"/v1/services/{service_id}/env-vars"),
            ("PUT", f"/v1/services/{service_id}/env-vars"),
        ]
        async with aiohttp.ClientSession() as s:
            for method, path in paths:
                try:
                    if method == "POST":
                        await self._post(s, path, json_body=payload_list)
                    elif method == "PATCH":
                        await self._patch(s, path, json_body=payload_list)
                    elif method == "PUT":
                        await self._put(s, path, json_body=payload_list)
                    return True
                except Exception:
                    continue
        return False
