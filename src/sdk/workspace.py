"""Unified workspace — clone directories for batch and indexing operations.

Directory layout:
  local mode:  {CWD}/{repo_name}/                         (flat, no user nesting)
  cloud mode:  {base}/{user_id}/{scope}/{owner__{repo}}/

Wipe methods are no-ops in local mode (clones persist across calls).
Clone skips re-cloning in local mode (the directory is assumed present).
"""
from __future__ import annotations

import asyncio
import logging
import os
import shutil
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING, Awaitable, Callable, Optional

if TYPE_CHECKING:
    from sdk.storage.cache.base import Cache

logger = logging.getLogger(__name__)


class Workspace:
    def __init__(
        self,
        local: bool,
        base: Path,
        cache: "Cache | None" = None,
    ) -> None:
        self._local = local
        self._base = base
        self._cache = cache

    def _require_cache(self) -> "Cache":
        if self._cache is None:
            raise RuntimeError("Workspace.cache is required for batch operations")
        return self._cache

    @staticmethod
    def _safe(repo: str) -> str:
        return repo.replace("/", "__")

    # -- Directory primitives ------------------------------------------------

    def repo_dir(self, user_id: str, scope: str, repo: str) -> Path:
        if self._local:
            return self._base / repo.rsplit("/", 1)[-1]
        return self._base / user_id / scope / self._safe(repo)

    def scope_dir(self, user_id: str, scope: str) -> Path:
        if self._local:
            return self._base
        return self._base / user_id / scope

    def prepare(self, user_id: str, scope: str) -> Path:
        d = self.scope_dir(user_id, scope)
        d.mkdir(parents=True, exist_ok=True)
        return d

    def wipe_user(self, user_id: str) -> None:
        if self._local:
            return
        d = self._base / user_id
        if d.exists():
            shutil.rmtree(d, ignore_errors=True)

    def wipe_scope(self, user_id: str, scope: str) -> None:
        if self._local:
            return
        d = self.scope_dir(user_id, scope)
        if d.exists():
            shutil.rmtree(d, ignore_errors=True)

    def wipe_repo(self, user_id: str, scope: str, repo: str) -> None:
        if self._local:
            return
        d = self.repo_dir(user_id, scope, repo)
        if d.exists():
            shutil.rmtree(d, ignore_errors=True)
            logger.info("Wiped workspace for %s/%s", user_id, repo)

    async def clone(
        self,
        user_id: str,
        scope: str,
        repo: str,
        token: str,
        branch: str | None = None,
        *,
        resume: bool = False,
    ) -> Path:
        """Clone repo into workspace.

        resume=True: skip re-clone if dir exists (batch path).
        resume=False: always wipe and re-clone (indexer path).
        Local mode: returns dir immediately without cloning.
        """
        dest = self.repo_dir(user_id, scope, repo)

        if self._local:
            logger.info("Local mode: reusing %s for %s", dest, repo)
            return dest

        if resume and dest.exists():
            logger.info("Workspace exists for %s — resuming", repo)
            return dest

        if dest.exists():
            shutil.rmtree(dest)

        dest.parent.mkdir(parents=True, exist_ok=True)
        url = f"https://x-access-token:{token}@github.com/{repo}.git"
        logger.info("Cloning %s branch=%s into %s", repo, branch, dest)

        cmd = ["git", "clone", "--depth", "1", "--no-recurse-submodules"]
        if branch:
            cmd.extend(["--branch", branch, "--single-branch"])
        cmd.extend([url, str(dest)])

        env = {**os.environ, "GIT_LFS_SKIP_SMUDGE": "1"}
        try:
            await asyncio.to_thread(
                subprocess.run,
                cmd,
                capture_output=True,
                text=True,
                check=True,
                env=env,
            )
        except subprocess.CalledProcessError as exc:
            scrubbed = exc.stderr.replace(token, "***") if token else exc.stderr
            raise RuntimeError(f"git clone failed for {repo}: {scrubbed.strip()}") from exc

        return dest

    # -- Batch operations ----------------------------------------------------

    async def propose(
        self,
        user_id: str,
        query: str,
        repos: list[str],
        *,
        get_token: Callable[[], Awaitable[str]],
    ):
        from sdk.batch.plan import ProposeRequest, propose
        return await propose(
            ProposeRequest(user_id=user_id, query=query, repos=repos),
            cache=self._require_cache(),
            get_token=get_token,
        )

    async def replan(self, user_id: str, hint: str):
        from sdk.batch.plan import ReplanRequest, replan
        return await replan(
            ReplanRequest(user_id=user_id, hint=hint),
            cache=self._require_cache(),
        )

    async def set_repo_subtask(
        self,
        user_id: str,
        repo: str,
        description: Optional[str],
        branch: Optional[str],
    ):
        from sdk.batch.plan import SetSubtaskRequest, set_repo_subtask
        return await set_repo_subtask(
            repo,
            SetSubtaskRequest(user_id=user_id, description=description, branch=branch),
            cache=self._require_cache(),
            workspace=self,
        )

    async def add_repos(
        self,
        user_id: str,
        repos: list[str],
        *,
        get_token: Callable[[], Awaitable[str]],
    ):
        from sdk.batch.plan import add_repos
        from sdk.batch.models import BulkReposRequest
        return await add_repos(
            BulkReposRequest(user_id=user_id, repos=repos),
            cache=self._require_cache(),
            get_token=get_token,
        )

    async def remove_repos(self, user_id: str, repos: list[str]):
        from sdk.batch.plan import remove_repos
        from sdk.batch.models import BulkReposRequest
        return await remove_repos(
            BulkReposRequest(user_id=user_id, repos=repos),
            cache=self._require_cache(),
            workspace=self,
        )

    async def start_diffs(
        self,
        user_id: str,
        *,
        get_token: Callable[[], Awaitable[str]],
    ):
        from sdk.batch.diff import start_diffs
        from sdk.batch.models import SimpleUserRequest
        return await start_diffs(
            SimpleUserRequest(user_id=user_id),
            cache=self._require_cache(),
            get_token=get_token,
            workspace=self,
        )

    async def chat_repo(self, user_id: str, repo: str, message: str, mode: str):
        from sdk.batch.diff import ChatRepoRequest, chat_repo
        return await chat_repo(
            repo,
            ChatRepoRequest(user_id=user_id, message=message, mode=mode),
            cache=self._require_cache(),
            workspace=self,
        )

    async def push_repos(
        self,
        user_id: str,
        repos: list[str],
        branch: Optional[str],
        force: bool,
        *,
        get_token: Callable[[], Awaitable[str]],
    ):
        from sdk.batch.push import PushReposRequest, push_repos
        return await push_repos(
            PushReposRequest(user_id=user_id, repos=repos, branch=branch, force=force),
            cache=self._require_cache(),
            get_token=get_token,
            workspace=self,
        )

    async def create_pr_prep(self, user_id: str, repos: list[str]):
        from sdk.batch.pr import CreatePRPrepRequest, create_pr_prep
        return await create_pr_prep(
            CreatePRPrepRequest(user_id=user_id, repos=repos),
            cache=self._require_cache(),
        )

    async def set_pr_prep(
        self,
        user_id: str,
        repo: str,
        title: Optional[str],
        body: Optional[str],
    ):
        from sdk.batch.pr import SetPRPrepRequest, set_pr_prep
        return await set_pr_prep(
            repo,
            SetPRPrepRequest(user_id=user_id, title=title, body=body),
            cache=self._require_cache(),
        )

    async def create_pr(
        self,
        user_id: str,
        repos: list[str],
        draft: bool,
        *,
        get_token: Callable[[], Awaitable[str]],
    ):
        from sdk.batch.pr import CreatePRRequest, create_pr
        return await create_pr(
            CreatePRRequest(user_id=user_id, repos=repos, draft=draft),
            cache=self._require_cache(),
            get_token=get_token,
            workspace=self,
        )

    async def update_pr(
        self,
        user_id: str,
        repo: str,
        title: Optional[str],
        body: Optional[str],
        *,
        get_token: Callable[[], Awaitable[str]],
    ):
        from sdk.batch.pr import UpdatePRRequest, update_pr
        return await update_pr(
            repo,
            UpdatePRRequest(user_id=user_id, title=title, body=body),
            cache=self._require_cache(),
            get_token=get_token,
        )

    async def close_pr(
        self,
        user_id: str,
        repos: list[str],
        *,
        get_token: Callable[[], Awaitable[str]],
    ):
        from sdk.batch.pr import close_pr
        from sdk.batch.models import BulkReposRequest
        return await close_pr(
            BulkReposRequest(user_id=user_id, repos=repos),
            cache=self._require_cache(),
            get_token=get_token,
        )

    async def current_session(self, user_id: str):
        from sdk.errors import NotFoundError
        session = await self._require_cache().get_session(user_id)
        if session is None:
            raise NotFoundError("No active batch session")
        return session

    async def cancel(self, user_id: str) -> dict:
        from sdk.batch import tasks as _tasks_mod
        _tasks_mod.cancel(user_id)
        cache = self._require_cache()
        await cache.wipe(user_id)
        await asyncio.to_thread(self.wipe_user, user_id)
        return {"status": "wiped"}

    async def inspect(
        self,
        user_id: str,
        view: str,
        *,
        get_token: Callable[[], Awaitable[str]],
        repos=None,
        repo=None,
        file=None,
        fmt=None,
    ):
        from sdk.batch.inspect import inspect_batch
        return await inspect_batch(
            user_id, view,
            repos=repos, repo=repo, file=file, fmt=fmt,
            cache=self._require_cache(),
            get_token=get_token,
        )

    async def get_ci_status(
        self,
        user_id: str,
        *,
        get_token: Callable[[], Awaitable[str]],
        repos=None,
        branch=None,
        pr_number=None,
        limit: int = 10,
    ):
        from sdk.batch.ci import get_ci_status
        return await get_ci_status(
            user_id,
            repos=repos, branch=branch, pr_number=pr_number, limit=limit,
            cache=self._require_cache(),
            get_token=get_token,
        )

    async def get_ci_jobs(
        self,
        user_id: str,
        repository: str,
        run_id: int,
        *,
        get_token: Callable[[], Awaitable[str]],
    ):
        from sdk.batch.ci import get_ci_jobs
        return await get_ci_jobs(user_id, repository, run_id, get_token=get_token)
