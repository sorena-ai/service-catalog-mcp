"""Inspect dispatch — status, PR status, diff file."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any, Awaitable, Callable, Optional

from sdk.errors import InvalidRequestError, NotFoundError
from sdk.batch.models import (
    BatchSessionConcise,
    PushState,
    SubTask,
)

if TYPE_CHECKING:
    from sdk.storage.cache.base import Cache

from lib.github.prs import get_pull_request

logger = logging.getLogger(__name__)


async def inspect_batch(
    user_id: str,
    view: str,
    repos: Optional[list[str]] = None,
    repo: Optional[str] = None,
    file: Optional[str] = None,
    fmt: Optional[str] = None,
    *,
    cache: "Cache",
    get_token: Callable[[], Awaitable[str]],
) -> Any:
    if view == "pr_status" and not repos:
        raise InvalidRequestError("view=pr_status requires repos")
    if view == "diff_file" and (not repo or not file):
        raise InvalidRequestError("view=diff_file requires repo and file")

    session = await cache.get_session(user_id)
    if session is None:
        raise NotFoundError("No active batch session")

    if view == "status":
        if fmt == "detailed":
            return session
        return BatchSessionConcise.from_session(session)

    if view == "pr_status":
        token = await get_token()

        async def _refresh_pr(r: str) -> None:
            sub = session.sub_tasks.get(r)
            if sub is None or sub.pr is None:
                return
            try:
                pr = await get_pull_request(repo=r, pr_number=sub.pr.number, token=token)
                await cache.set_subtask(user_id, r, SubTask(
                    repo=r, branch=sub.branch, description=sub.description,
                    diff=sub.diff, push=sub.push, pr_prep=sub.pr_prep, pr=pr,
                ))
            except Exception:
                logger.exception("inspect pr_status: failed for %s/%s", user_id, r)

        await asyncio.gather(*[_refresh_pr(r) for r in repos])
        return await cache.get_session(user_id)

    # view == "diff_file"
    diff = await cache.get_raw_diff(user_id, repo, file)
    if diff is None:
        raise NotFoundError(f"No diff stored for {repo}/{file}")
    return diff
