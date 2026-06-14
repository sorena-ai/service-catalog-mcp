"""Plan-phase operations — propose, replan, add/remove repos, set subtask."""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Awaitable, Callable, Optional

from pydantic import BaseModel, field_validator

from sdk.errors import ConflictError, InvalidRequestError, NotFoundError
from sdk.batch.models import BatchSession, Hint, SubTask, Task

if TYPE_CHECKING:
    from sdk.storage.cache.base import Cache

from . import tasks as _tasks_mod
from .llms.planner import run_planner
from .models import BulkReposRequest
from .workspace import wipe_repo_workspace
from lib.github.repos import get_default_branch

logger = logging.getLogger(__name__)


class ProposeRequest(BaseModel):
    user_id: str
    query: str
    repos: list[str]

    @field_validator("repos")
    @classmethod
    def repos_not_empty(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("repos must not be empty")
        return v


class ReplanRequest(BaseModel):
    user_id: str
    hint: str


class SetSubtaskRequest(BaseModel):
    user_id: str
    description: Optional[str] = None
    branch: Optional[str] = None


async def propose(req: ProposeRequest, *, cache: "Cache", get_token: Callable[[], Awaitable[str]]) -> BatchSession:
    existing = await cache.get_session(req.user_id)
    if existing:
        raise ConflictError("Active session exists; call cancel_batch first")

    session_id = str(uuid.uuid4())
    sub_tasks_skeleton: dict[str, SubTask] = {}
    for repo in req.repos:
        sub_tasks_skeleton[repo] = SubTask(repo=repo, branch="main", description="")

    skeleton = BatchSession(
        user_id=req.user_id,
        session_id=session_id,
        query=req.query,
        task=Task(description=""),
        history=[],
        sub_tasks=sub_tasks_skeleton,
        created_at=datetime.now(timezone.utc),
    )

    token = await get_token()
    branches = await asyncio.gather(
        *[get_default_branch(repo, token) for repo in req.repos]
    )
    for repo, branch in zip(req.repos, branches):
        skeleton.sub_tasks[repo] = SubTask(repo=repo, branch=branch, description="")

    planner_out = await run_planner(skeleton)

    for repo, sub in skeleton.sub_tasks.items():
        skeleton.sub_tasks[repo] = SubTask(
            repo=repo,
            branch=sub.branch,
            description=planner_out.per_repo_descriptions.get(repo, ""),
        )
    skeleton.task = Task(description=planner_out.task_description)

    await cache.set_meta(req.user_id, skeleton)
    for repo, sub in skeleton.sub_tasks.items():
        await cache.set_subtask(req.user_id, repo, sub)

    return await cache.get_session(req.user_id)


async def replan(req: ReplanRequest, *, cache: "Cache") -> BatchSession:
    session = await cache.get_session(req.user_id)
    if session is None:
        raise NotFoundError("No active batch session")
    session.history.append(Hint(text=req.hint, at=datetime.now(timezone.utc)))

    planner_out = await run_planner(session)

    session.task = Task(description=planner_out.task_description)
    for repo, sub in session.sub_tasks.items():
        new_desc = planner_out.per_repo_descriptions.get(repo, sub.description)
        session.sub_tasks[repo] = SubTask(
            repo=repo,
            branch=sub.branch,
            description=new_desc,
            diff=sub.diff,
            push=sub.push,
            pr_prep=sub.pr_prep,
            pr=sub.pr,
        )

    await cache.set_meta(req.user_id, session)
    for repo, sub in session.sub_tasks.items():
        await cache.set_subtask(req.user_id, repo, sub)

    return await cache.get_session(req.user_id)


async def set_repo_subtask(repo: str, req: SetSubtaskRequest, *, cache: "Cache") -> BatchSession:
    session = await cache.get_session(req.user_id)
    if session is None:
        raise NotFoundError("No active batch session")
    sub = session.sub_tasks.get(repo)
    if sub is None:
        raise NotFoundError(f"Repo {repo!r} not in session")

    branch_changed = req.branch is not None and req.branch != sub.branch
    new_branch = req.branch if req.branch is not None else sub.branch
    new_desc = req.description if req.description is not None else sub.description

    if branch_changed:
        _tasks_mod.cancel_repo(req.user_id, repo)
        wipe_repo_workspace(req.user_id, session.session_id, repo)
        updated = SubTask(repo=repo, branch=new_branch, description=new_desc)
    else:
        updated = SubTask(
            repo=repo,
            branch=new_branch,
            description=new_desc,
            diff=sub.diff,
            push=sub.push,
            pr_prep=sub.pr_prep,
            pr=sub.pr,
        )

    await cache.set_subtask(req.user_id, repo, updated)
    return await cache.get_session(req.user_id)


async def add_repos(req: BulkReposRequest, *, cache: "Cache", get_token: Callable[[], Awaitable[str]]) -> BatchSession:
    session = await cache.get_session(req.user_id)
    if session is None:
        raise NotFoundError("No active batch session")
    token = await get_token()

    new_repos = [r for r in req.repos if r not in session.sub_tasks]
    if not new_repos:
        return await cache.get_session(req.user_id)

    branches = await asyncio.gather(*[get_default_branch(r, token) for r in new_repos])

    extended = BatchSession(
        user_id=session.user_id,
        session_id=session.session_id,
        query=session.query,
        task=session.task,
        history=session.history,
        sub_tasks={
            **session.sub_tasks,
            **{r: SubTask(repo=r, branch=b, description="") for r, b in zip(new_repos, branches)},
        },
        created_at=session.created_at,
    )
    planner_out = await run_planner(extended)

    for r, b in zip(new_repos, branches):
        new_sub = SubTask(
            repo=r,
            branch=b,
            description=planner_out.per_repo_descriptions.get(r, ""),
        )
        await cache.set_subtask(req.user_id, r, new_sub)
        session.sub_tasks[r] = new_sub

    await cache.set_meta(req.user_id, session)
    return await cache.get_session(req.user_id)


async def remove_repos(req: BulkReposRequest, *, cache: "Cache") -> BatchSession:
    session = await cache.get_session(req.user_id)
    if session is None:
        raise NotFoundError("No active batch session")

    async def _remove_one(repo: str) -> None:
        if repo not in session.sub_tasks:
            return
        _tasks_mod.cancel_repo(req.user_id, repo)
        wipe_repo_workspace(req.user_id, session.session_id, repo)
        await cache.delete_subtask(req.user_id, repo)

    await asyncio.gather(*[_remove_one(r) for r in req.repos])
    return await cache.get_session(req.user_id)
