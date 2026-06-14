from __future__ import annotations

from typing import List, Optional

from fastmcp import Context
from fastmcp.exceptions import ToolError

from mcp_server.errors import translate_sdk_errors
from mcp_server.identity import get_service_manager
from sdk.batch.models import BatchSession


@translate_sdk_errors
async def create_pr_prep(ctx: Context, repos: List[str]) -> BatchSession:
    """Draft PR title+body for each repo via Haiku LLM (parallel).

    Inputs: task.description, sub_task.description, diff.one_line_summary,
    diff.file_stats. Writes to sub_task.pr_prep. No GitHub API call.
    Precondition: diff.status == "ready" for each repo.

    Args:
        repos: List of "owner/repo" strings to draft PR prep for.
    """
    if not repos:
        raise ToolError("repos must not be empty")
    sm = await get_service_manager(ctx)
    return await sm.create_pr_prep(repos)


@translate_sdk_errors
async def set_pr_prep(
    ctx: Context,
    repo: str,
    title: Optional[str] = None,
    body: Optional[str] = None,
) -> BatchSession:
    """Partial update of a repo's PR prep (title and/or body).

    Branch fields (head_branch, base_branch) are immutable here.
    Only supply fields you want to change. Returns updated BatchSession.

    Args:
        repo: "owner/repo" string.
        title: New PR title. Omit to keep existing.
        body: New PR body. Omit to keep existing.
    """
    sm = await get_service_manager(ctx)
    return await sm.set_pr_prep(repo, title, body)


@translate_sdk_errors
async def create_pr(ctx: Context, repos: List[str], draft: bool = False) -> BatchSession:
    """Open GitHub PRs for the given repos (parallel).

    Requires pr_prep and a successful push per repo. CONFIRM with the user
    before calling, especially for >5 repos.

    Args:
        repos: List of "owner/repo" strings to open PRs for. Must not be empty.
        draft: If True, opens as draft PR. Defaults to False.
    """
    if not repos:
        raise ToolError("repos must not be empty")
    sm = await get_service_manager(ctx)
    return await sm.create_pr(repos, draft)


@translate_sdk_errors
async def update_pr(
    ctx: Context,
    repo: str,
    title: Optional[str] = None,
    body: Optional[str] = None,
) -> BatchSession:
    """Update an open PR's title and/or body via GitHub API.

    Mirrors the change to pr_prep for local consistency. Draft conversion
    is not supported (requires GraphQL). Returns updated BatchSession.

    Args:
        repo: "owner/repo" string of the repo with an open PR.
        title: New PR title. Omit to keep existing.
        body: New PR body. Omit to keep existing.
    """
    sm = await get_service_manager(ctx)
    return await sm.update_pr(repo, title, body)


@translate_sdk_errors
async def close_pr(ctx: Context, repos: List[str]) -> BatchSession:
    """Close PRs without merging for the given repos.

    Sets PR state to closed on GitHub. Returns updated BatchSession.

    Args:
        repos: List of "owner/repo" strings whose PRs to close. Must not be empty.
    """
    if not repos:
        raise ToolError("repos must not be empty")
    sm = await get_service_manager(ctx)
    return await sm.close_pr(repos)
