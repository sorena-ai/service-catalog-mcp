from __future__ import annotations

from typing import Any, List, Optional

from fastmcp import Context

from mcp_server.errors import translate_sdk_errors
from mcp_server.identity import get_service_manager


@translate_sdk_errors
async def inspect_batch(
    ctx: Context,
    view: str,
    repos: Optional[List[str]] = None,
    repo: Optional[str] = None,
    file: Optional[str] = None,
    format: Optional[str] = None,
) -> Any:
    """Unified read tool — dispatches on view.

    view="status": Return session state. format="concise" (default) returns
    {repo: {phase, diff_status, push_status, pr_url}} map. format="detailed"
    returns the full BatchSession. Cheap — call freely to check progress.

    view="pr_status": Re-fetch PR state from GitHub for the given repos and
    update the session. Requires repos. Returns updated BatchSession.

    view="diff_file": Return the raw unified diff for one file. Requires repo
    and file. Only call when the user explicitly asks — diffs can be large.

    Args:
        view: One of "status", "pr_status", "diff_file".
        repos: Required for view=pr_status. List of "owner/repo" strings.
        repo: Required for view=diff_file. Single "owner/repo" string.
        file: Required for view=diff_file. File path within the repo.
        format: For view=status only. "concise" (default) or "detailed".
    """
    sm = await get_service_manager(ctx)
    result = await sm.inspect(view, repos=repos, repo=repo, file=file, fmt=format)
    if isinstance(result, str):
        return result
    return result.model_dump(mode="json")


@translate_sdk_errors
async def cancel_batch(ctx: Context) -> dict:
    """Cancel all in-flight tasks and wipe the session.

    Cancels CLI subprocesses, deletes Redis keys, removes workspace from disk.
    Already-created GitHub PRs are not touched. Returns {"status": "wiped"}.
    CONFIRM with the user before calling.
    """
    sm = await get_service_manager(ctx)
    return await sm.cancel()
