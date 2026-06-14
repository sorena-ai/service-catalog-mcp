"""Thin sync shim — preserves GitHubClient interface used by existing routes."""
from __future__ import annotations

import logging
from typing import Optional

import httpx

from lib.github.client import _make_jwt


class GitHubClient:
    def create_installation_access_token(self, installation_id: int | str) -> Optional[str]:
        """Return a short-lived GitHub installation access token (sync)."""
        url = f"https://api.github.com/app/installations/{installation_id}/access_tokens"
        headers = {
            "Authorization": f"Bearer {_make_jwt()}",
            "Accept": "application/vnd.github.v3+json",
        }
        try:
            with httpx.Client(timeout=15) as client:
                resp = client.post(url, headers=headers)
                resp.raise_for_status()
                return resp.json().get("token")
        except Exception as exc:
            logging.error("Error getting installation access token: %s", exc)
            return None
