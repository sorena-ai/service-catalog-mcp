"""Identity resolution for core.

Core receives identity from http-server via X-Core-Identity header.
This header contains the user email (for dashboard) or MCP client/session ID.
"""

import base64
import os
from typing import Optional
from fastapi import Query, HTTPException, Header, Request
from api.db.users import UserDB

GITHUB_APP_NAME = os.getenv("GITHUB_APP_NAME", "service-catalog")


def _build_install_url(user_id: str) -> str:
    state = base64.urlsafe_b64encode(user_id.encode()).decode()
    return f"https://github.com/apps/{GITHUB_APP_NAME}/installations/new?state={state}"


def require_install_for(user_id: str):
    """Check user exists and has GitHub App installed. Returns user. Raises 404 or 412."""
    user = UserDB().get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if not user.installation_id:
        raise HTTPException(
            status_code=412,
            detail={
                "reason": "github_app_not_installed",
                "install_url": _build_install_url(user_id),
                "message": "GitHub App is not installed for this user.",
            },
        )
    return user


def require_user_for(user_id: str):
    """Check user exists. Returns user. Raises 404."""
    user = UserDB().get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


def require_install_q(user_id: str = Query(...)):
    """FastAPI dependency for GET routes: reads user_id from query param, checks install."""
    return require_install_for(user_id)


def require_user_q(user_id: str = Query(...)):
    """FastAPI dependency for GET routes: reads user_id from query param, checks user exists."""
    return require_user_for(user_id)


def require_user_id(user_id: Optional[str] = Query(None)) -> str:
    """Dependency for GET endpoints — reads user_id from query param."""
    if not user_id:
        raise HTTPException(status_code=401, detail="user_id is required")
    return user_id


def optional_user_id(user_id: Optional[str] = Query(None)) -> Optional[str]:
    return user_id


def require_auth(x_core_identity: Optional[str] = Header(None)) -> dict:
    """Dependency for endpoints requiring authentication via X-Core-Identity header.

    Returns a dict with 'id' field containing the identity (email or MCP client/session).
    """
    if not x_core_identity:
        raise HTTPException(status_code=401, detail="X-Core-Identity header is required")
    return {"id": x_core_identity}


def auth_optional(x_core_identity: Optional[str] = Header(None)) -> Optional[dict]:
    """Optional auth dependency. Returns dict with 'id' if present, otherwise None."""
    if x_core_identity:
        return {"id": x_core_identity}
    return None


def get_user_email(request: Request) -> str:
    """Extract user email from X-Core-Identity header."""
    identity = request.headers.get("X-Core-Identity")
    if not identity:
        raise HTTPException(status_code=401, detail="X-Core-Identity header is required")
    return identity
