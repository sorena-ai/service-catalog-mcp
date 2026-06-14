"""GitHub App authentication — JWT generation and installation access tokens."""
from __future__ import annotations

import asyncio
import os
import time

import httpx
import jwt

_PRIVATE_KEY_CACHE: str | None = None


def _app_id() -> str:
    return os.environ["GITHUB_APP_ID"]


def _private_key() -> str:
    global _PRIVATE_KEY_CACHE
    if _PRIVATE_KEY_CACHE is None:
        path = os.environ["GITHUB_PRIVATE_KEY_PATH"]
        with open(path) as f:
            _PRIVATE_KEY_CACHE = f.read()
    return _PRIVATE_KEY_CACHE


def _make_jwt() -> str:
    now = int(time.time())
    payload = {"iat": now - 60, "exp": now + (9 * 60), "iss": _app_id()}
    return jwt.encode(payload, _private_key(), algorithm="RS256")


async def installation_token_for_id(installation_id: int | str) -> str:
    """Exchange a GitHub App JWT for a short-lived installation access token."""
    url = f"https://api.github.com/app/installations/{installation_id}/access_tokens"
    headers = {
        "Authorization": f"Bearer {_make_jwt()}",
        "Accept": "application/vnd.github.v3+json",
    }
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(url, headers=headers)
        resp.raise_for_status()
        return resp.json()["token"]


async def installation_token(user_id: str) -> str:
    """Resolve user_id → installation_id → short-lived token."""
    from api.db.users import UserDB  # noqa: PLC0415

    user_db = UserDB()
    user = await asyncio.to_thread(user_db.get_user_by_id, user_id)
    if user is None or not user.installation_id:
        raise ValueError(f"No GitHub installation for user {user_id}")
    return await installation_token_for_id(user.installation_id)
