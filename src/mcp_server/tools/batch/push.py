from __future__ import annotations

from typing import List, Optional

from fastmcp import Context
from fastmcp.exceptions import ToolError

from mcp_server.errors import translate_sdk_errors
from mcp_server.identity import get_service_manager
from sdk.batch.models import BatchSession


@translate_sdk_errors
async def push_repos(
    ctx: Context,
    repos: List[str],
    branch: Optional[str] = None,
    force: bool = False,
) -> BatchSession:
    """Push the given repos' diffs to GitHub branches, then return the BatchSession.

    Creates a commit on a PR branch and pushes it. Skips repos whose diff is
    not ready or whose push already succeeded. CONFIRM with the user before
    calling, especially for >1 repo.

    Args:
        repos: List of "owner/repo" strings to push. Must not be empty.
        branch: PR branch name override. Defaults to "service-catalog/batch-{session_id[:8]}".
        force: If True, allows targeting the repo's default branch. Defaults to False.
    """
    if not repos:
        raise ToolError("repos must not be empty")
    sm = await get_service_manager(ctx)
    return await sm.push_repos(repos, branch, force)
