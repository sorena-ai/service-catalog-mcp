"""Per-user and per-user-per-repo asyncio.Task registry."""

from __future__ import annotations

import asyncio
import logging

logger = logging.getLogger(__name__)

# User-level tasks (propose, replan)
_user_tasks: dict[str, asyncio.Task] = {}

# Repo-level tasks: (user_id, repo) → Task
_repo_tasks: dict[tuple[str, str], asyncio.Task] = {}


# ---------------------------------------------------------------------------
# User-level registry
# ---------------------------------------------------------------------------

def register(user_id: str, task: asyncio.Task) -> None:
    existing = _user_tasks.get(user_id)
    if existing and not existing.done():
        existing.cancel()
        logger.info("Cancelled prior user task for %s", user_id)
    _user_tasks[user_id] = task


def cancel(user_id: str) -> None:
    task = _user_tasks.pop(user_id, None)
    if task and not task.done():
        task.cancel()
        logger.info("Cancelled user task for %s", user_id)
    # Also cancel all repo-level tasks for this user
    cancel_all_repos(user_id)


# ---------------------------------------------------------------------------
# Repo-level registry
# ---------------------------------------------------------------------------

def register_repo(user_id: str, repo: str, task: asyncio.Task) -> None:
    key = (user_id, repo)
    existing = _repo_tasks.get(key)
    if existing and not existing.done():
        existing.cancel()
        logger.info("Cancelled prior repo task for %s/%s", user_id, repo)
    _repo_tasks[key] = task


def cancel_repo(user_id: str, repo: str) -> None:
    key = (user_id, repo)
    task = _repo_tasks.pop(key, None)
    if task and not task.done():
        task.cancel()
        logger.info("Cancelled repo task for %s/%s", user_id, repo)


def cancel_all_repos(user_id: str) -> None:
    keys = [k for k in _repo_tasks if k[0] == user_id]
    for key in keys:
        task = _repo_tasks.pop(key, None)
        if task and not task.done():
            task.cancel()
            logger.info("Cancelled repo task for %s/%s", user_id, key[1])
