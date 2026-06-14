"""Per-event temporary clone workspace for indexing.

Creates and manages a scoped directory layout that isolates indexing events
from each other:

    {INDEX_CLONE_BASE_DIR}/{user_id}/{event_id}/{repo_safe_name}/

The workspace is intentionally thin. It does not clone concurrently, retry, or
resolve identity; callers (e.g. the indexing orchestrator) compose those.

It is also used outside the indexer when ephemeral repo clones are needed.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

DEFAULT_BASE_DIR = "/tmp/index-workspace"


def _base_dir() -> Path:
    return Path(os.environ.get("INDEX_CLONE_BASE_DIR", DEFAULT_BASE_DIR)).resolve()


def _safe_name(repository_name: str) -> str:
    """Flatten ``org/name`` into a single directory segment."""
    return repository_name.replace("/", "__")


class IndexCloneWorkspace:
    def __init__(self, user_id: str):
        if not user_id:
            raise ValueError("user_id is required")
        self.user_id = user_id
        self.base_dir = _base_dir()
        self.user_dir = self.base_dir / user_id

    def event_dir(self, event_id: str) -> Path:
        if not event_id:
            raise ValueError("event_id is required")
        return self.user_dir / event_id

    def repo_dir(self, event_id: str, repository_name: str) -> Path:
        return self.event_dir(event_id) / _safe_name(repository_name)

    def prepare(self, event_id: str) -> Path:
        event = self.event_dir(event_id)
        event.mkdir(parents=True, exist_ok=True)
        logger.debug("Prepared index workspace event dir: %s", event)
        return event

    def clone_repo(
        self,
        event_id: str,
        repository_name: str,
        token: str,
        branch: Optional[str] = None,
    ) -> Path:
        """Shallow-clone ``repository_name`` into the event dir.

        Default branch is used unless ``branch`` is given. LFS smudge and
        submodules are skipped.
        """
        self.prepare(event_id)
        target = self.repo_dir(event_id, repository_name)
        if target.exists():
            shutil.rmtree(target)

        clone_url = f"https://x-access-token:{token}@github.com/{repository_name}"
        cmd = [
            "git",
            "clone",
            "--depth",
            "1",
            "--no-recurse-submodules",
            clone_url,
            str(target),
        ]
        if branch:
            cmd.extend(["--branch", branch, "--single-branch"])

        env = {**os.environ, "GIT_LFS_SKIP_SMUDGE": "1"}
        try:
            subprocess.run(cmd, capture_output=True, text=True, check=True, env=env)
        except subprocess.CalledProcessError as exc:
            # Don't echo the URL (contains token) — log only stderr.
            logger.error(
                "Shallow clone failed for %s (event=%s): %s",
                repository_name,
                event_id,
                exc.stderr,
            )
            raise RuntimeError(
                f"Failed to clone {repository_name}: {exc.stderr.strip()}"
            ) from exc

        logger.info(
            "Cloned %s into %s (event=%s)", repository_name, target, event_id
        )
        return target

    def cleanup(self, event_id: str) -> None:
        event = self.event_dir(event_id)
        # Safety guard: only delete inside our base dir.
        try:
            event.resolve().relative_to(self.base_dir)
        except ValueError:
            logger.error(
                "Refusing to clean event dir outside base: %s (base=%s)",
                event,
                self.base_dir,
            )
            return
        if event.exists():
            shutil.rmtree(event)
            logger.debug("Cleaned up index workspace event dir: %s", event)
