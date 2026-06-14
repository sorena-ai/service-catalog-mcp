"""GitHub PR CRUD — create, update, get, close."""
from __future__ import annotations

from datetime import datetime

import httpx

from lib.github.models import PR


def _parse_pr(data: dict) -> PR:
    state = "merged" if data.get("merged") else data["state"]
    return PR(
        number=data["number"],
        url=data["html_url"],
        state=state,
        is_draft=data.get("draft", False),
        opened_at=datetime.fromisoformat(data["created_at"].replace("Z", "+00:00")),
    )


async def create_pull_request(
    repo: str,
    head_branch: str,
    base_branch: str,
    title: str,
    body: str,
    draft: bool,
    token: str,
) -> PR:
    """Create a PR; on 422 'already exists', find and update the existing one."""
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github.v3+json"}
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"https://api.github.com/repos/{repo}/pulls",
            headers=headers,
            json={"title": title, "body": body, "head": head_branch, "base": base_branch, "draft": draft},
        )
        if resp.status_code == 422:
            err = resp.json()
            err_text = err.get("message", "") + " ".join(
                e.get("message", "") for e in err.get("errors", [])
            )
            if "already exists" in err_text:
                owner = repo.split("/")[0]
                find = await client.get(
                    f"https://api.github.com/repos/{repo}/pulls",
                    headers=headers,
                    params={"head": f"{owner}:{head_branch}", "state": "open"},
                )
                find.raise_for_status()
                existing = find.json()
                if existing:
                    patch = await client.patch(
                        f"https://api.github.com/repos/{repo}/pulls/{existing[0]['number']}",
                        headers=headers,
                        json={"title": title, "body": body},
                    )
                    patch.raise_for_status()
                    return _parse_pr(patch.json())
            resp.raise_for_status()
        else:
            resp.raise_for_status()
        return _parse_pr(resp.json())


async def update_pull_request(
    repo: str,
    pr_number: int,
    token: str,
    title: str | None = None,
    body: str | None = None,
) -> PR:
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github.v3+json"}
    payload = {k: v for k, v in {"title": title, "body": body}.items() if v is not None}
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.patch(
            f"https://api.github.com/repos/{repo}/pulls/{pr_number}",
            headers=headers,
            json=payload,
        )
        resp.raise_for_status()
        return _parse_pr(resp.json())


async def get_pull_request(repo: str, pr_number: int, token: str) -> PR:
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github.v3+json"}
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(
            f"https://api.github.com/repos/{repo}/pulls/{pr_number}",
            headers=headers,
        )
        resp.raise_for_status()
        return _parse_pr(resp.json())


async def get_pr_head_sha(repo: str, pr_number: int, token: str) -> str:
    """Return the head commit SHA of a pull request."""
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github.v3+json"}
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(
            f"https://api.github.com/repos/{repo}/pulls/{pr_number}",
            headers=headers,
        )
        resp.raise_for_status()
        return resp.json()["head"]["sha"]


async def close_pull_request(repo: str, pr_number: int, token: str) -> PR:
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github.v3+json"}
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.patch(
            f"https://api.github.com/repos/{repo}/pulls/{pr_number}",
            headers=headers,
            json={"state": "closed"},
        )
        resp.raise_for_status()
        return _parse_pr(resp.json())
