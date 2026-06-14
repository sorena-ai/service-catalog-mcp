"""On-disk workspace management for per-batch clone directories."""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
from pathlib import Path

from git import GitCommandError, Repo

logger = logging.getLogger(__name__)

BASE = Path(os.getenv("BATCH_CLONE_BASE_DIR", "/var/batch-workspaces"))


def user_dir(user_id: str) -> Path:
    return BASE / user_id


def session_dir(user_id: str, session_id: str) -> Path:
    return user_dir(user_id) / session_id


def repo_dir(user_id: str, session_id: str, repo: str) -> Path:
    return session_dir(user_id, session_id) / repo.replace("/", "__")


def wipe_user(user_id: str) -> None:
    d = user_dir(user_id)
    if d.exists():
        shutil.rmtree(d, ignore_errors=True)


def wipe_repo_workspace(user_id: str, session_id: str, repo: str) -> None:
    d = repo_dir(user_id, session_id, repo)
    if d.exists():
        shutil.rmtree(d, ignore_errors=True)
        logger.info("Wiped workspace for %s/%s", user_id, repo)


async def clone_repo(user_id: str, session_id: str, repo: str, branch: str, token: str) -> Path:
    """Clone repo into workspace dir. If the dir already exists, skip — resume path."""
    dest = repo_dir(user_id, session_id, repo)
    if dest.exists():
        logger.info("Workspace already exists for %s — resuming", repo)
        return dest

    dest.parent.mkdir(parents=True, exist_ok=True)
    url = f"https://x-access-token:{token}@github.com/{repo}.git"
    logger.info("Cloning %s branch=%s into %s", repo, branch, dest)
    try:
        await asyncio.to_thread(
            Repo.clone_from,
            url,
            str(dest),
            branch=branch,
            depth=1,
        )
    except GitCommandError as exc:
        scrubbed = str(exc).replace(token, "***")
        raise RuntimeError(f"git clone failed for {repo}: {scrubbed}") from None
    return dest
