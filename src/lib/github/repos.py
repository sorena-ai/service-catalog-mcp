"""Repository metadata helpers."""
from __future__ import annotations

import httpx


async def get_default_branch(repo: str, token: str) -> str:
    """Return the default branch name for owner/repo."""
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github.v3+json"}
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(f"https://api.github.com/repos/{repo}", headers=headers)
        resp.raise_for_status()
        return resp.json()["default_branch"]
