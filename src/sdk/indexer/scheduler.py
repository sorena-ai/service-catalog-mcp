"""Per-user indexing event scheduler.

Coalesces bursts of triggers into a single event per user, enforces the
single-in-flight rule, and applies the auto-index bulk limit. The
orchestrator's ``run_indexing_event`` is a long, awaitable coroutine; the
scheduler is the only place that decides when (and whether) to invoke it.

Behavior:

  - Triggers add their repos to a per-user pending set.
  - If no event is in flight for the user, a debounce timer starts (default
    60s). New triggers within the window cancel + restart the timer so a
    burst converges into one event.
  - When the timer fires, the scheduler acquires the per-user lock, drains
    pending repos, and runs the orchestrator.
  - Triggers arriving while a run is in flight just append to pending; the
    scheduler loops after the current run completes.
  - The bulk auto-index limit (5 repos) only applies when ``bulk_limit`` is
    True. Manual single-repo triggers pass it through unconditionally.
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
    DEFAULT_DEBOUNCE_SECONDS = 60.0

    def __init__(self, debounce_seconds: float = DEFAULT_DEBOUNCE_SECONDS) -> None:
        self.debounce_seconds = debounce_seconds
        self._pending_repos: Dict[str, Set[str]] = {}
        self._pending_token: Dict[str, TokenProvider] = {}
        self._pending_trigger: Dict[str, str] = {}
        self._timers: Dict[str, asyncio.Task] = {}
        self._locks: Dict[str, asyncio.Lock] = {}
        self._tasks: Set[asyncio.Task] = set()

    def _lock(self, user_id: str) -> asyncio.Lock:
        if user_id not in self._locks:
            self._locks[user_id] = asyncio.Lock()
        return self._locks[user_id]

    async def trigger(
        self,
        user_id: str,
        repository_names: List[str],
        token_provider: TokenProvider,
        trigger: str = "auto",
        bulk_limit: bool = True,
    ) -> dict:
        """Schedule (or coalesce) an indexing event for ``user_id``.

        Returns a status dict describing what happened. ``token_provider``
        is invoked at run time so installation tokens are always fresh.
        """
        if not repository_names:
            return {"status": "no_repos"}

        if bulk_limit and len(repository_names) > self.AUTO_INDEX_BULK_LIMIT:
            logger.info(
                "Bulk auto-index limit hit for user=%s (%d repos > %d); skipping",
                user_id, len(repository_names), self.AUTO_INDEX_BULK_LIMIT,
            )
            return {
                "status": "skipped_bulk_limit",
                "limit": self.AUTO_INDEX_BULK_LIMIT,
                "repo_count": len(repository_names),
            }

        self._pending_repos.setdefault(user_id, set()).update(repository_names)
        self._pending_token[user_id] = token_provider
        self._pending_trigger[user_id] = trigger

        if self._lock(user_id).locked():
            return {
                "status": "queued_dirty",
                "pending_count": len(self._pending_repos[user_id]),
            }

        existing = self._timers.get(user_id)
        if existing and not existing.done():
            existing.cancel()

        timer = asyncio.create_task(self._debounced_run(user_id))
        self._timers[user_id] = timer
        self._tasks.add(timer)
        timer.add_done_callback(self._tasks.discard)
        return {
            "status": "scheduled",
            "pending_count": len(self._pending_repos[user_id]),
        }

    async def _debounced_run(self, user_id: str) -> None:
        try:
            await asyncio.sleep(self.debounce_seconds)
        except asyncio.CancelledError:
            return

        async with self._lock(user_id):
            while True:
                repos = self._pending_repos.pop(user_id, None)
                token = self._pending_token.pop(user_id, None)
                trigger = self._pending_trigger.pop(user_id, "auto")

                if not repos or token is None:
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
                # Loop iff trigger() added more pending while we were running.

    async def shutdown(self) -> None:
        for timer in list(self._timers.values()):
            timer.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)


# Module-level singleton used by the FastAPI app.
indexing_scheduler = IndexingScheduler()
