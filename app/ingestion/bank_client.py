from __future__ import annotations

from typing import Any

import httpx

from app.core.config import get_settings


class AgrobankClient:
    def __init__(self) -> None:
        settings = get_settings()
        self.settings = settings

        self.client = httpx.AsyncClient(
            timeout=httpx.Timeout(
                30.0,
                connect=10.0,
            ),
            follow_redirects=True,
            headers={
                "User-Agent": "AgrobankRAGBot/0.1 (+backend ingestion)",
            },
        )

    async def close(self) -> None:
        await self.client.aclose()

    async def get_menu(self) -> dict[str, Any]:
        response = await self.client.get(
            self.settings.bank_menu_url,
        )
        response.raise_for_status()

        data = response.json()

        if not isinstance(data, dict):
            raise ValueError(
                "menu.json did not return a JSON object"
            )

        return data

    async def get_page(
        self,
        code: str,
    ) -> dict[str, Any]:
        response = await self.client.get(
            self.settings.bank_api_url,
            params={
                "action": "pages",
                "code": code.lstrip("/"),
            },
        )
        response.raise_for_status()

        data = response.json()

        if not isinstance(data, dict):
            raise ValueError(
                f"Page API returned non-object JSON for {code}"
            )

        return data