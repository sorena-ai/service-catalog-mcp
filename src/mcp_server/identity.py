"""Identity resolution — resolves (user_id, get_token) per request.

LOCAL=true (default): single-user local mode, PAT from GITHUB_TOKEN.
LOCAL=false: cloud mode, Auth0 JWT → Mongo → per-user installation token.
"""
from __future__ import annotations

import base64
import logging
import os
from typing import Awaitable, Callable, Tuple

from fastmcp import Context
from fastmcp.server.dependencies import get_access_token

from sdk.errors import GitHubAppNotInstalledError

log = logging.getLogger("mcp_server.identity")

_LOCAL_MODE: bool = os.getenv("LOCAL", "true").lower() in ("1", "true", "yes")

if not _LOCAL_MODE and not os.getenv("MONGODB_URI"):
    raise RuntimeError("MONGODB_URI must be set when running in cloud mode (LOCAL=false)")

_LOCAL_TOKEN: str = os.getenv("GITHUB_TOKEN", "") if _LOCAL_MODE else ""

_USER_ID_STATE_KEY = "resolved_user_id"


def _build_install_url(user_id: str) -> str:
    github_app_name = os.getenv("GITHUB_APP_NAME", "service-catalog")
    state = base64.urlsafe_b64encode(user_id.encode()).decode()
    return f"https://github.com/apps/{github_app_name}/installations/new?state={state}"


def ensure_installed(user_id: str) -> None:
    if _LOCAL_MODE:
        return
    from api.db.users import UserDB
    user = UserDB().get_user_by_id(user_id)
    if not user or not user.installation_id:
        raise GitHubAppNotInstalledError(install_url=_build_install_url(user_id))


async def resolve_identity(
    ctx: Context,
) -> Tuple[str, Callable[[], Awaitable[str]]]:
    """Return (user_id, get_token) for this request."""
    if _LOCAL_MODE:
        if not _LOCAL_TOKEN:
            raise RuntimeError("GITHUB_TOKEN env var is not set. Required for local mode.")

        async def _get_token() -> str:
            return _LOCAL_TOKEN

        return "default", _get_token

    cached = await ctx.get_state(_USER_ID_STATE_KEY)
    if cached:
        user_id = cached
    else:
        access_token = get_access_token()
        if access_token is None:
            raise RuntimeError("No authenticated token — MCP_AUTH0_DOMAIN must be configured")
        auth0_sub = access_token.claims.get("sub", "")
        email = access_token.claims.get("email")
        name = access_token.claims.get("name")
        if not auth0_sub:
            raise RuntimeError("Token missing 'sub' claim")

        from api.db.users import UserDB
        user, _ = UserDB().resolve_or_create_from_auth0(auth0_sub, email=email, name=name)
        user_id = user.user_id
        await ctx.set_state(_USER_ID_STATE_KEY, user_id)

    async def _get_token() -> str:
        from api.db.users import UserDB
        from lib.github.client import installation_token_for_id
        user = UserDB().get_user_by_id(user_id)
        if not user or not user.installation_id:
            raise GitHubAppNotInstalledError(install_url=_build_install_url(user_id))
        return await installation_token_for_id(user.installation_id)

    return user_id, _get_token
