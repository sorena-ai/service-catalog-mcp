from __future__ import annotations

from typing import List, Optional

from fastmcp import Context
from fastmcp.exceptions import ToolError
from pydantic import BaseModel

from mcp_server.errors import translate_sdk_errors
from mcp_server.identity import get_service_manager
from sdk.batch.models import BatchSession

_PLAN_NEXT_STEP = (
    "Present the task description and each repo's subtask description to the user, "
    "then ask them to choose:\n"
    "  1. Adjust the plan — call replan, set_repo_subtask, add_repos, or remove_repos\n"
    "  2. Approve and start — call start_diffs\n"
    "Do NOT call start_diffs until the user explicitly picks option 2."
)


class PlanResponse(BaseModel):
    """Returned by all plan-phase tools. Always stop and present before proceeding."""
    session: BatchSession
    next_step: str = _PLAN_NEXT_STEP


@translate_sdk_errors
async def propose_plan(ctx: Context, query: str, repos: List[str]) -> PlanResponse:
    """Propose a batch code change plan across the given repositories.

    Fetches default branches in parallel, then runs the planner LLM to generate
    per-repo task descriptions. Returns a PlanResponse with the plan inside.
    Blocks ~3–10s. Returns 409 if a session already exists — call cancel_batch
    first to clear it.

    IMPORTANT: After this returns, present the plan to the user and ask them to
    choose between adjusting it or approving it. Do NOT call start_diffs until
    the user explicitly approves.

    Args:
        query: Natural-language description of the change to make.
        repos: List of "owner/repo" strings. Must not be empty — call
               search_repos first to find affected repositories.
    """
    if not repos:
        raise ToolError("repos must not be empty")
    sm = await get_service_manager(ctx)
    return PlanResponse(session=await sm.propose(query, repos))


@translate_sdk_errors
async def replan(ctx: Context, hint: str) -> PlanResponse:
    """Re-run the planner with an additional hint appended to session history.

    Use for any scope change or refinement — small tweak or total pivot.
    Preserves existing diff/push/PR state per repo. Returns updated plan.

    IMPORTANT: After this returns, present the updated plan to the user and ask
    them to choose between adjusting further or approving. Do NOT call
    start_diffs until the user explicitly approves.

    Args:
        hint: Additional context or change directive for the planner, e.g.
              "also update docker-compose.yml in each repo".
    """
    sm = await get_service_manager(ctx)
    return PlanResponse(session=await sm.replan(hint))


@translate_sdk_errors
async def set_repo_subtask(
    ctx: Context,
    repo: str,
    description: Optional[str] = None,
    branch: Optional[str] = None,
) -> PlanResponse:
    """Directly edit one repo's task description or base branch.

    Changing branch cascades: wipes that repo's workspace, diff, and push state.
    Only supply fields you want to change. Returns updated plan.

    IMPORTANT: After this returns, present the updated plan to the user and ask
    them to choose between adjusting further or approving. Do NOT call
    start_diffs until the user explicitly approves.

    Args:
        repo: "owner/repo" string identifying the repository.
        description: New per-repo task notes. Replaces the planner output.
        branch: New base branch (PR target). Triggers workspace wipe if changed.
    """
    sm = await get_service_manager(ctx)
    return PlanResponse(session=await sm.set_repo_subtask(repo, description, branch))


@translate_sdk_errors
async def add_repos(ctx: Context, repos: List[str]) -> PlanResponse:
    """Add repositories to the current session mid-batch.

    Fetches default branches and runs the planner to fill descriptions for the
    new repos only (existing repos are unaffected). Idempotent — already-present
    repos are silently skipped. New repos land with diff=None; call start_diffs
    again to kick off their CLI runs.

    IMPORTANT: After this returns, present the updated plan to the user and ask
    them to choose between adjusting further or approving. Do NOT call
    start_diffs until the user explicitly approves.

    Args:
        repos: List of "owner/repo" strings to add. Must not be empty.
    """
    if not repos:
        raise ToolError("repos must not be empty")
    sm = await get_service_manager(ctx)
    return PlanResponse(session=await sm.add_repos(repos))


@translate_sdk_errors
async def remove_repos(ctx: Context, repos: List[str]) -> BatchSession:
    """Remove repositories from the session.

    Cancels any in-flight CLI for each repo, wipes workspaces and Redis keys.
    Already-created GitHub PRs are not touched. Silently skips repos not in the
    session. Returns the updated BatchSession.

    Args:
        repos: List of "owner/repo" strings to remove. Must not be empty.
    """
    if not repos:
        raise ToolError("repos must not be empty")
    sm = await get_service_manager(ctx)
    return await sm.remove_repos(repos)
