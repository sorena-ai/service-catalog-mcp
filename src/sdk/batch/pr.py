"""PR-phase operations — prep, create, update, close."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Awaitable, Callable, List, Optional

from pydantic import BaseModel

from sdk.errors import ConflictError, NotFoundError
from sdk.batch.models import PR, PRPrep, SubTask

if TYPE_CHECKING:
    from sdk.storage.cache.base import Cache
    from sdk.workspace import Workspace

from .llms.pr_drafter import draft_pr
from .models import BulkReposRequest
from .push import pr_branch_name, push_repo
from lib.github.prs import (
    close_pull_request,
    create_pull_request,
    update_pull_request,
)

logger = logging.getLogger(__name__)


class CreatePRPrepRequest(BaseModel):
    user_id: str
    repos: List[str]


class SetPRPrepRequest(BaseModel):
    user_id: str
    title: Optional[str] = None
    body: Optional[str] = None


class CreatePRRequest(BaseModel):
    user_id: str
    repos: list[str]
    draft: bool = False


class UpdatePRRequest(BaseModel):
    user_id: str
    title: Optional[str] = None
    body: Optional[str] = None


# ---------------------------------------------------------------------------
# PR prep endpoints
# ---------------------------------------------------------------------------


async def create_pr_prep(req: CreatePRPrepRequest, *, cache: "Cache"):
    from sdk.batch.models import BatchSession

    session = await cache.get_session(req.user_id)
    if session is None:
        raise NotFoundError("No active batch session")

    async def _draft_one(repo: str) -> None:
        sub = session.sub_tasks.get(repo)
        if sub is None:
            logger.warning("create_pr_prep: repo %s not in session for user %s", repo, req.user_id)
            return
        if sub.diff is None or sub.diff.status != "ready":
            logger.warning("create_pr_prep: repo %s diff not ready (%s)", repo, sub.diff and sub.diff.status)
            return
        try:
            out = await draft_pr(
                task_description=session.task.description,
                sub_task_description=sub.description,
                one_line_summary=sub.diff.one_line_summary or "",
                file_stats=sub.diff.file_stats,
            )
            prep = PRPrep(
                title=out.title,
                body=out.body,
                head_branch=pr_branch_name(session.session_id),
                base_branch=sub.branch,
            )
            updated = SubTask(
                repo=repo, branch=sub.branch, description=sub.description,
                diff=sub.diff, push=sub.push, pr_prep=prep, pr=sub.pr,
            )
            await cache.set_subtask(req.user_id, repo, updated)
        except Exception:
            logger.exception("create_pr_prep: drafting failed for %s/%s", req.user_id, repo)

    await asyncio.gather(*[_draft_one(repo) for repo in req.repos])
    return await cache.get_session(req.user_id)


async def set_pr_prep(repo: str, req: SetPRPrepRequest, *, cache: "Cache"):
    from sdk.batch.models import BatchSession

    session = await cache.get_session(req.user_id)
    if session is None:
        raise NotFoundError("No active batch session")
    sub = session.sub_tasks.get(repo)
    if sub is None:
        raise NotFoundError(f"Repo {repo!r} not in session")
    if sub.pr_prep is None:
        raise ConflictError("No pr_prep for this repo; call create_pr_prep first")

    updated_prep = PRPrep(
        title=req.title if req.title is not None else sub.pr_prep.title,
        body=req.body if req.body is not None else sub.pr_prep.body,
        head_branch=sub.pr_prep.head_branch,
        base_branch=sub.pr_prep.base_branch,
    )
    updated = SubTask(
        repo=repo, branch=sub.branch, description=sub.description,
        diff=sub.diff, push=sub.push, pr_prep=updated_prep, pr=sub.pr,
    )
    await cache.set_subtask(req.user_id, repo, updated)
    return await cache.get_session(req.user_id)


# ---------------------------------------------------------------------------
# PR endpoints
# ---------------------------------------------------------------------------


async def create_pr(req: CreatePRRequest, *, cache: "Cache", get_token: Callable[[], Awaitable[str]], workspace: "Workspace"):
    from sdk.batch.models import BatchSession

    session = await cache.get_session(req.user_id)
    if session is None:
        raise NotFoundError("No active batch session")
    token = await get_token()

    async def _open_one(repo: str) -> None:
        sub = session.sub_tasks.get(repo)
        if sub is None:
            logger.warning("create_pr: repo %s not in session", repo)
            return
        if sub.pr_prep is None:
            logger.warning("create_pr: repo %s has no pr_prep", repo)
            return
        await push_repo(req.user_id, session.session_id, repo, None, False,
                        cache=cache, get_token=get_token, workspace=workspace)
        sub = await cache.get_subtask(req.user_id, repo)
        if sub is None or sub.push is None or sub.push.status != "pushed":
            logger.warning("create_pr: push failed for %s, skipping PR", repo)
            return
        try:
            pr = PR.model_validate((await create_pull_request(
                repo=repo,
                head_branch=sub.pr_prep.head_branch,
                base_branch=sub.pr_prep.base_branch,
                title=sub.pr_prep.title,
                body=sub.pr_prep.body,
                draft=req.draft,
                token=token,
            )).model_dump())
            updated = SubTask(
                repo=repo, branch=sub.branch, description=sub.description,
                diff=sub.diff, push=sub.push, pr_prep=sub.pr_prep, pr=pr,
            )
            await cache.set_subtask(req.user_id, repo, updated)
        except Exception:
            logger.exception("create_pr: failed for %s/%s", req.user_id, repo)

    await asyncio.gather(*[_open_one(repo) for repo in req.repos])
    return await cache.get_session(req.user_id)


async def update_pr(repo: str, req: UpdatePRRequest, *, cache: "Cache", get_token: Callable[[], Awaitable[str]]):
    from sdk.batch.models import BatchSession

    session = await cache.get_session(req.user_id)
    if session is None:
        raise NotFoundError("No active batch session")
    sub = session.sub_tasks.get(repo)
    if sub is None:
        raise NotFoundError(f"Repo {repo!r} not in session")
    if sub.pr is None:
        raise ConflictError("No PR for this repo; call create_pr first")

    token = await get_token()
    pr = PR.model_validate((await update_pull_request(
        repo=repo, pr_number=sub.pr.number, token=token,
        title=req.title, body=req.body,
    )).model_dump())

    updated_prep = sub.pr_prep
    if sub.pr_prep is not None:
        updated_prep = PRPrep(
            title=req.title if req.title is not None else sub.pr_prep.title,
            body=req.body if req.body is not None else sub.pr_prep.body,
            head_branch=sub.pr_prep.head_branch,
            base_branch=sub.pr_prep.base_branch,
        )

    updated = SubTask(
        repo=repo, branch=sub.branch, description=sub.description,
        diff=sub.diff, push=sub.push, pr_prep=updated_prep, pr=pr,
    )
    await cache.set_subtask(req.user_id, repo, updated)
    return await cache.get_session(req.user_id)


async def close_pr(req: BulkReposRequest, *, cache: "Cache", get_token: Callable[[], Awaitable[str]]):
    from sdk.batch.models import BatchSession

    session = await cache.get_session(req.user_id)
    if session is None:
        raise NotFoundError("No active batch session")
    token = await get_token()

    async def _close_one(repo: str) -> None:
        sub = session.sub_tasks.get(repo)
        if sub is None or sub.pr is None:
            logger.warning("close_pr: repo %s has no PR", repo)
            return
        try:
            pr = PR.model_validate((await close_pull_request(repo=repo, pr_number=sub.pr.number, token=token)).model_dump())
            updated = SubTask(
                repo=repo, branch=sub.branch, description=sub.description,
                diff=sub.diff, push=sub.push, pr_prep=sub.pr_prep, pr=pr,
            )
            await cache.set_subtask(req.user_id, repo, updated)
        except Exception:
            logger.exception("close_pr: failed for %s/%s", req.user_id, repo)

    await asyncio.gather(*[_close_one(repo) for repo in req.repos])
    return await cache.get_session(req.user_id)
