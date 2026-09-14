"""Per-repo push logic + push_repos orchestration."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Awaitable, Callable, Optional

from pydantic import BaseModel
from git import Actor, GitCommandError, Repo

from sdk.batch.models import BatchSession, PushState
from sdk.errors import NotFoundError

if TYPE_CHECKING:
    from sdk.storage.cache.base import Cache
    from sdk.workspace import Workspace

logger = logging.getLogger(__name__)

_BOT = Actor("Service Catalog", "bot@infraas.ai")


class PushReposRequest(BaseModel):
    user_id: str
    repos: list[str]
    branch: Optional[str] = None
    force: bool = False


def pr_branch_name(session_id: str) -> str:
    return f"service-catalog/batch-{session_id[:8]}"


async def push_repo(
    user_id: str,
    session_id: str,
    repo: str,
    branch_override: str | None = None,
    force: bool = False,
    *,
    cache: "Cache",
    get_token: Callable[[], Awaitable[str]],
    workspace: "Workspace",
) -> None:
    """Commit all changes on a PR branch and push to origin. Writes PushState to cache."""
    sub = await cache.get_subtask(user_id, repo)
    if sub is None:
        logger.warning("push_repo: subtask %s/%s not found", user_id, repo)
        return

    cwd = workspace.repo_dir(user_id, session_id, repo)
    branch = branch_override or pr_branch_name(session_id)

    if branch == sub.branch and not force:
        await cache.set_subtask(user_id, repo, sub.model_copy(update={
            "push": PushState(
                status="failed", branch=branch, at=datetime.now(timezone.utc),
                error=f"Branch '{branch}' is the default branch; pass force=true to override",
            ),
        }))
        return

    await cache.set_subtask(user_id, repo, sub.model_copy(update={
        "push": PushState(status="pushing", branch=branch, at=datetime.now(timezone.utc)),
    }))

    token = await get_token()
    try:
        pushed_sha = await asyncio.to_thread(_do_push, cwd, repo, branch, sub.description, token)
        await cache.set_subtask(user_id, repo, sub.model_copy(update={
            "push": PushState(
                status="pushed", branch=branch, pushed_sha=pushed_sha,
                at=datetime.now(timezone.utc),
            ),
        }))
        logger.info("Pushed %s/%s → %s@%s", user_id, repo, branch, pushed_sha[:7])

    except GitCommandError as exc:
        scrubbed = str(exc).replace(token, "***")
        logger.error("Push failed for %s/%s: %s", user_id, repo, scrubbed)
        await cache.set_subtask(user_id, repo, sub.model_copy(update={
            "push": PushState(
                status="failed", branch=branch, at=datetime.now(timezone.utc),
                error=scrubbed[:500],
            ),
        }))
    except Exception:
        logger.exception("Push failed for %s/%s", user_id, repo)
        await cache.set_subtask(user_id, repo, sub.model_copy(update={
            "push": PushState(
                status="failed", branch=branch, at=datetime.now(timezone.utc),
                error="Internal error during push (see server logs)",
            ),
        }))


async def push_repos(req: PushReposRequest, *, cache: "Cache", get_token: Callable[[], Awaitable[str]], workspace: "Workspace") -> BatchSession:
    session = await cache.get_session(req.user_id)
    if session is None:
        raise NotFoundError("No active batch session")

    pushable = [
        repo for repo in req.repos
        if repo in session.sub_tasks
        and session.sub_tasks[repo].diff is not None
        and session.sub_tasks[repo].diff.status == "ready"
        and (
            session.sub_tasks[repo].push is None
            or session.sub_tasks[repo].push.status == "failed"
        )
    ]
    await asyncio.gather(*[
        push_repo(req.user_id, session.session_id, repo, req.branch, req.force,
                  cache=cache, get_token=get_token, workspace=workspace)
        for repo in pushable
    ])
    return await cache.get_session(req.user_id)


def _do_push(cwd: Path, repo_name: str, branch: str, commit_message: str, token: str) -> str:
    """Stage all changes, commit on a PR branch, push to origin. Returns pushed SHA."""
    r = Repo(str(cwd))

    # Stage everything: new, modified, deleted — respects .gitignore
    r.git.add(A=True)

    # Create/reset PR branch at current HEAD tip (force=True handles the retry path)
    r.create_head(branch, force=True)
    r.head.reference = r.heads[branch]

    # Commit only if there are staged changes
    if r.index.diff(r.head.commit):
        r.index.commit(
            commit_message,
            author=_BOT,
            committer=_BOT,
        )
    else:
        logger.info("Nothing to commit for %s branch %s", repo_name, branch)

    remote_url = f"https://x-access-token:{token}@github.com/{repo_name}.git"
    refspec = f"refs/heads/{branch}:refs/heads/{branch}"
    r.git.push(remote_url, refspec, force=True)

    return r.head.commit.hexsha
