"""Per-user indexing basket.

Each user has one *basket* of repositories awaiting indexing. Repos added to a
user's basket are picked up immediately — there is no debounce timer and no
polling delay. A single worker runs per user, so one indexing event is in
flight at a time for a given user; different users index concurrently.

While a worker is running, repos added to that user's basket are drained by the
same worker in a back-to-back run the instant the current event finishes, so
the worker keeps going until the basket is empty.

Note: because an indexing event is internally phased (clone → codebase pass →
scan → repo pass), a repo added mid-event is not folded into the *running*
event's passes — it is processed by the immediately-following run instead.

Caveat: the basket is in-memory. If the process restarts, pending repos are
lost (they remain ``indexing_status="pending"`` in Mongo and must be
re-triggered). Persisting the basket (e.g. in Redis) is a possible follow-up.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable, Dict, List, Set

from .orchestrator import run_indexing_event

logger = logging.getLogger(__name__)

TokenProvider = Callable[[str], Awaitable[str]]


class IndexingScheduler:
    AUTO_INDEX_BULK_LIMIT = 5

    def __init__(self) -> None:
        self._baskets: Dict[str, Set[str]] = {}
        self._token: Dict[str, TokenProvider] = {}
        self._trigger: Dict[str, str] = {}
        self._workers: Dict[str, asyncio.Task] = {}

    async def trigger(
        self,
        user_id: str,
        repository_names: List[str],
        token_provider: TokenProvider,
        trigger: str = "auto",
        bulk_limit: bool = True,
    ) -> dict:
        """Add ``repository_names`` to ``user_id``'s basket and ensure a worker
        is running. Starts indexing immediately if the user has no worker yet;
        otherwise the running worker picks the repos up when it drains next.

        ``token_provider`` is invoked at run time so installation tokens are
        always fresh.
        """
        if not repository_names:
            return {"status": "no_repos"}

        if bulk_limit and len(repository_names) > self.AUTO_INDEX_BULK_LIMIT:
            logger.info(
                "Bulk auto-index limit hit for user=%s (%d > %d); skipping",
                user_id, len(repository_names), self.AUTO_INDEX_BULK_LIMIT,
            )
            return {
                "status": "skipped_bulk_limit",
                "limit": self.AUTO_INDEX_BULK_LIMIT,
                "repo_count": len(repository_names),
            }

        self._baskets.setdefault(user_id, set()).update(repository_names)
        self._token[user_id] = token_provider
        self._trigger[user_id] = trigger

        worker = self._workers.get(user_id)
        if worker and not worker.done():
            return {"status": "added", "basket_size": len(self._baskets[user_id])}

        worker = asyncio.create_task(self._drain(user_id))
        self._workers[user_id] = worker
        return {"status": "started", "basket_size": len(self._baskets[user_id])}

    async def _drain(self, user_id: str) -> None:
        """Run indexing events back-to-back until the user's basket is empty.

        The basket-empty check and the worker removal below run without an
        intervening ``await``, so a concurrent ``trigger()`` (single-threaded
        asyncio) cannot leave repos stranded with no worker.
        """
        while True:
            repos = self._baskets.pop(user_id, None)
            token = self._token.pop(user_id, None)
            trigger = self._trigger.pop(user_id, "auto")

            if not repos or token is None:
                self._workers.pop(user_id, None)
                return

            try:
                await run_indexing_event(
                    user_id=user_id,
                    repository_names=sorted(repos),
                    token_provider=token,
                    trigger=trigger,
                )
            except Exception:
                logger.exception(
                    "Indexing event raised; user=%s repos=%d", user_id, len(repos)
                )

    async def shutdown(self) -> None:
        workers = list(self._workers.values())
        for worker in workers:
            worker.cancel()
        await asyncio.gather(*workers, return_exceptions=True)


# Module-level singleton used by the FastAPI app.
indexing_scheduler = IndexingScheduler()
