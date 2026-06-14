"""ServiceManager — shared backends + per-request user identity.

Constructed once per request in mcp_server/identity.py and injected into
every tool call. Exposes all batch and search operations as flat methods.
"""

from __future__ import annotations

from typing import Awaitable, Callable, Optional

from sdk.storage.cache.base import Cache


class ServiceManager:
    def __init__(
        self,
        *,
        cache: Cache,
        repos: object,
        user_id: str,
        get_token: Callable[[], Awaitable[str]],
    ) -> None:
        self.cache = cache
        self.repos = repos
        self.user_id = user_id
        self.get_token = get_token

    # -------------------------------------------------------------------------
    # Batch — plan
    # -------------------------------------------------------------------------

    async def propose(self, query: str, repos: list[str]):
        from sdk.batch.plan import ProposeRequest, propose
        return await propose(
            ProposeRequest(user_id=self.user_id, query=query, repos=repos),
            cache=self.cache,
            get_token=self.get_token,
        )

    async def replan(self, hint: str):
        from sdk.batch.plan import ReplanRequest, replan
        return await replan(
            ReplanRequest(user_id=self.user_id, hint=hint),
            cache=self.cache,
        )

    async def set_repo_subtask(self, repo: str, description: Optional[str], branch: Optional[str]):
        from sdk.batch.plan import SetSubtaskRequest, set_repo_subtask
        return await set_repo_subtask(
            repo,
            SetSubtaskRequest(user_id=self.user_id, description=description, branch=branch),
            cache=self.cache,
        )

    async def add_repos(self, repos: list[str]):
        from sdk.batch.plan import add_repos
        from sdk.batch.models import BulkReposRequest
        return await add_repos(
            BulkReposRequest(user_id=self.user_id, repos=repos),
            cache=self.cache,
            get_token=self.get_token,
        )

    async def remove_repos(self, repos: list[str]):
        from sdk.batch.plan import remove_repos
        from sdk.batch.models import BulkReposRequest
        return await remove_repos(
            BulkReposRequest(user_id=self.user_id, repos=repos),
            cache=self.cache,
        )

    # -------------------------------------------------------------------------
    # Batch — diff
    # -------------------------------------------------------------------------

    async def start_diffs(self):
        from sdk.batch.diff import start_diffs
        from sdk.batch.models import SimpleUserRequest
        return await start_diffs(
            SimpleUserRequest(user_id=self.user_id),
            cache=self.cache,
            get_token=self.get_token,
        )

    async def chat_repo(self, repo: str, message: str, mode: str):
        from sdk.batch.diff import ChatRepoRequest, chat_repo
        return await chat_repo(
            repo,
            ChatRepoRequest(user_id=self.user_id, message=message, mode=mode),
            cache=self.cache,
        )

    # -------------------------------------------------------------------------
    # Batch — push
    # -------------------------------------------------------------------------

    async def push_repos(self, repos: list[str], branch: Optional[str], force: bool):
        from sdk.batch.push import PushReposRequest, push_repos
        return await push_repos(
            PushReposRequest(user_id=self.user_id, repos=repos, branch=branch, force=force),
            cache=self.cache,
            get_token=self.get_token,
        )

    # -------------------------------------------------------------------------
    # Batch — PR
    # -------------------------------------------------------------------------

    async def create_pr_prep(self, repos: list[str]):
        from sdk.batch.pr import CreatePRPrepRequest, create_pr_prep
        return await create_pr_prep(
            CreatePRPrepRequest(user_id=self.user_id, repos=repos),
            cache=self.cache,
        )

    async def set_pr_prep(self, repo: str, title: Optional[str], body: Optional[str]):
        from sdk.batch.pr import SetPRPrepRequest, set_pr_prep
        return await set_pr_prep(
            repo,
            SetPRPrepRequest(user_id=self.user_id, title=title, body=body),
            cache=self.cache,
        )

    async def create_pr(self, repos: list[str], draft: bool):
        from sdk.batch.pr import CreatePRRequest, create_pr
        return await create_pr(
            CreatePRRequest(user_id=self.user_id, repos=repos, draft=draft),
            cache=self.cache,
            get_token=self.get_token,
        )

    async def update_pr(self, repo: str, title: Optional[str], body: Optional[str]):
        from sdk.batch.pr import UpdatePRRequest, update_pr
        return await update_pr(
            repo,
            UpdatePRRequest(user_id=self.user_id, title=title, body=body),
            cache=self.cache,
            get_token=self.get_token,
        )

    async def close_pr(self, repos: list[str]):
        from sdk.batch.pr import close_pr
        from sdk.batch.models import BulkReposRequest
        return await close_pr(
            BulkReposRequest(user_id=self.user_id, repos=repos),
            cache=self.cache,
            get_token=self.get_token,
        )

    # -------------------------------------------------------------------------
    # Batch — session
    # -------------------------------------------------------------------------

    async def current_session(self):
        from sdk.errors import NotFoundError
        session = await self.cache.get_session(self.user_id)
        if session is None:
            raise NotFoundError("No active batch session")
        return session

    async def cancel(self) -> dict:
        from sdk.batch import tasks as _tasks_mod
        from sdk.batch.workspace import wipe_user
        _tasks_mod.cancel(self.user_id)
        await self.cache.wipe(self.user_id)
        wipe_user(self.user_id)
        return {"status": "wiped"}

    async def inspect(self, view: str, repos=None, repo=None, file=None, fmt=None):
        from sdk.batch.inspect import inspect_batch
        return await inspect_batch(
            self.user_id, view,
            repos=repos, repo=repo, file=file, fmt=fmt,
            cache=self.cache,
            get_token=self.get_token,
        )

    # -------------------------------------------------------------------------
    # Batch — CI
    # -------------------------------------------------------------------------

    async def get_ci_status(self, repos=None, branch=None, pr_number=None, limit=10):
        from sdk.batch.ci import get_ci_status
        return await get_ci_status(
            self.user_id,
            repos=repos, branch=branch, pr_number=pr_number, limit=limit,
            cache=self.cache,
            get_token=self.get_token,
        )

    async def get_ci_jobs(self, repository: str, run_id: int):
        from sdk.batch.ci import get_ci_jobs
        return await get_ci_jobs(self.user_id, repository, run_id, get_token=self.get_token)

    # -------------------------------------------------------------------------
    # Search
    # -------------------------------------------------------------------------

    def search_repos(self, filters=None, nl_query: Optional[str] = None, limit: int = 20):
        from sdk.search.service import IndexSearchService
        from sdk.search.models import SearchResultNL
        svc = IndexSearchService()
        if nl_query:
            return svc.public_search_with_nl(self.user_id, nl_query, limit=limit)
        result = svc.public_search(self.user_id, filters, limit=limit)
        return SearchResultNL(
            exact_matches=result.exact_matches,
            near_matches=result.near_matches,
            not_found=result.not_found,
        )

    def get_codebase_glossary(self):
        from sdk.search.service import IndexSearchService
        return IndexSearchService().get_codebase_glossary(self.user_id)
