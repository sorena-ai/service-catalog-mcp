from __future__ import annotations

import asyncio
import logging
from typing import Literal

from fastmcp import Context

from mcp_server.errors import translate_sdk_errors
from mcp_server.identity import resolve_identity
from sdk.batch.models import BatchSession, SubTask

log = logging.getLogger("mcp_server.batch")

_DIFF_WEIGHT: dict[str, float] = {
    "pending": 0.0,
    "cloning": 0.2,
    "running": 0.7,
    "ready":   1.0,
    "failed":  1.0,
}
_DIFF_DEADLINE = 25.0
_DIFF_POLL = 1.0


def _diffs_all_terminal(sub_tasks: dict[str, SubTask]) -> bool:
    for sub in sub_tasks.values():
        if sub.diff is not None and sub.diff.status not in ("ready", "failed"):
            return False
    return True


def _diff_progress(sub_tasks: dict[str, SubTask]) -> tuple[float, int, str]:
    pieces: list[str] = []
    weighted = 0.0
    for repo, sub in sub_tasks.items():
        state = sub.diff.status if sub.diff is not None else "pending"
        weighted += _DIFF_WEIGHT.get(state, 0.0)
        pieces.append(f"{repo}: {state}")
    return weighted, len(sub_tasks), " | ".join(pieces)


@translate_sdk_errors
async def start_diffs(ctx: Context) -> BatchSession:
    """Kick off the Claude CLI for every repo whose diff is still pending.

    Only call this after the user has explicitly approved the plan in conversation.
    Background: returns immediately. Use wait_for_diffs() to track progress.
    Idempotent — already-running or terminal repos are skipped.
    """
    ws = ctx.lifespan_context["workspace"]
    user_id, get_token = await resolve_identity(ctx)
    return await ws.start_diffs(user_id, get_token=get_token)


@translate_sdk_errors
async def chat_repo(
    ctx: Context,
    repo: str,
    message: str,
    mode: Literal["qa", "edit"],
):
    """Resume the repo's Claude CLI session with a message.

    mode="qa": Q&A only — ask questions about the diff or codebase.
    Does not recollect the diff; one_line_summary is unchanged.

    mode="edit": Send an edit instruction. Recollects the diff afterward,
    updates file_stats and one_line_summary. Returns updated session on success.
    On failure: status="failed", cli_response contains the error — no exception raised.

    Args:
        repo: "owner/repo" string. Must have an active CLI session (diff started).
        message: The message to send to the Claude CLI session.
        mode: "qa" for questions, "edit" for code changes.
    """
    ws = ctx.lifespan_context["workspace"]
    user_id, _ = await resolve_identity(ctx)
    return await ws.chat_repo(user_id, repo, message, mode)


@translate_sdk_errors
async def wait_for_diffs(ctx: Context) -> BatchSession:
    """Stream per-repo diff progress for ~25s, then return the current BatchSession.

    Emits one MCP progress notification per state change. Progress is a weighted
    sum: pending=0, cloning=0.2, running=0.7, ready/failed=1.0 per repo.

    IMPORTANT: If the returned session still has repos in non-terminal state,
    call this tool again — it is safe to call repeatedly until all diffs complete.
    """
    ws = ctx.lifespan_context["workspace"]
    user_id, _ = await resolve_identity(ctx)

    loop = asyncio.get_running_loop()
    start = loop.time()
    last_progress = -1.0
    last_message = ""

    while True:
        session = await ws.current_session(user_id)

        weighted, total, message = _diff_progress(session.sub_tasks)
        progress = max(weighted, last_progress)

        if message != last_message:
            if progress <= last_progress:
                progress = last_progress + 0.0001
            try:
                await ctx.report_progress(
                    progress=progress,
                    total=float(total or 1),
                    message=message,
                )
            except Exception:
                pass
            last_progress = progress
            last_message = message

        if _diffs_all_terminal(session.sub_tasks):
            return session

        if loop.time() - start > _DIFF_DEADLINE:
            return session

        await asyncio.sleep(_DIFF_POLL)
