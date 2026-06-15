"""CI status — one-shot fetch, write into session, return per-repo CIState."""
from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Awaitable, Callable, Optional

import httpx
from pydantic import BaseModel

from sdk.errors import InvalidRequestError, NotFoundError
from sdk.batch.models import CIState, PushState, SubTask, WorkflowJob

if TYPE_CHECKING:
    from sdk.storage.cache.base import Cache

logger = logging.getLogger(__name__)


class RepoCIResult(BaseModel):
    """Per-repo CI fetch outcome — exactly one of ci/error is set."""
    ci: Optional[CIState] = None
    error: Optional[str] = None


def _err_msg(exc: Exception) -> str:
    if isinstance(exc, httpx.HTTPStatusError):
        return f"GitHub API returned {exc.response.status_code}"
    return str(exc) or exc.__class__.__name__


async def get_ci_status(
    user_id: str,
    repos: Optional[list[str]] = None,
    branch: Optional[str] = None,
    pr_number: Optional[int] = None,
    limit: int = 10,
    *,
    cache: "Cache",
    get_token: Callable[[], Awaitable[str]],
) -> dict[str, RepoCIResult]:
    """Fetch CI for repos, write CIState into session, return per-repo result.

    If repos is None, targets all repos with a successful push in the active
    session. If no session exists and repos is None, raises NotFoundError.
    """
    from lib.github.actions import fetch_workflow_runs
    from lib.github.prs import get_pr_head_sha

    token = await get_token()

    if repos is None:
        session = await cache.get_session(user_id)
        if session is None:
            raise NotFoundError("No active batch session")
        targets = [
            r for r, sub in session.sub_tasks.items()
            if sub.push is not None and sub.push.status == "pushed"
        ]
        if not targets:
            raise InvalidRequestError("No pushed repos in the current session")
    else:
        targets = repos
        session = await cache.get_session(user_id)

    async def _fetch_one(repo: str) -> tuple[str, RepoCIResult]:
        sub = session.sub_tasks.get(repo) if session else None
        head_sha: Optional[str] = None
        fetch_branch: Optional[str] = None

        if sub and sub.push and sub.push.pushed_sha:
            head_sha = sub.push.pushed_sha
        elif pr_number is not None:
            try:
                head_sha = await get_pr_head_sha(repo, pr_number, token)
            except Exception as exc:
                logger.exception("ci: failed to resolve PR head SHA for %s", repo)
                return repo, RepoCIResult(error=f"Could not resolve PR #{pr_number}: {_err_msg(exc)}")
        else:
            fetch_branch = branch

        try:
            raw_ci = await fetch_workflow_runs(repo, token, head_sha=head_sha, branch=fetch_branch, limit=limit)
            ci = CIState.model_validate(raw_ci.model_dump())
        except Exception as exc:
            logger.exception("ci: failed to fetch for %s", repo)
            return repo, RepoCIResult(error=_err_msg(exc))

        if sub is not None and sub.push is not None:
            updated_push = PushState(
                status=sub.push.status,
                branch=sub.push.branch,
                pushed_sha=sub.push.pushed_sha,
                at=sub.push.at,
                error=sub.push.error,
                ci=ci,
            )
            await cache.set_subtask(user_id, repo, SubTask(
                repo=repo, branch=sub.branch, description=sub.description,
                diff=sub.diff, push=updated_push, pr_prep=sub.pr_prep, pr=sub.pr,
            ))
        return repo, RepoCIResult(ci=ci)

    results = await asyncio.gather(*[_fetch_one(r) for r in targets])
    return dict(results)


async def get_ci_jobs(
    user_id: str,
    repo: str,
    run_id: int,
    *,
    get_token: Callable[[], Awaitable[str]],
) -> list[WorkflowJob]:
    """Fetch jobs for a specific workflow run."""
    from lib.github.actions import fetch_workflow_jobs
    token = await get_token()
    return await fetch_workflow_jobs(repo, run_id, token)
