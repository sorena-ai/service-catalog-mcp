"""Shared file walker used by deterministic scanners.

Walks a cloned repo and yields ``(rel_path, size_bytes)`` for each file.
Ignores common build, cache, and tooling directories. Stops yielding new
files once ``max_files`` is reached so a pathological repo cannot blow past
Mongo's 16MB doc limit when serialized into ``repository_trees.paths``.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Iterator, Tuple

# Directories never worth walking. Match by basename.
IGNORE_DIRS = frozenset({
    ".git",
    ".hg",
    ".svn",
    "node_modules",
    "bower_components",
    "vendor",
    "__pycache__",
    ".venv",
    "venv",
    ".env",
    ".tox",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".cache",
    "dist",
    "build",
    "out",
    "target",
    ".next",
    ".nuxt",
    ".svelte-kit",
    ".turbo",
    ".gradle",
    ".idea",
    ".vscode",
    ".terraform",
})

# Hard ceiling. ~50k paths × ~80 chars ≈ 4MB serialized.
DEFAULT_MAX_FILES = 50_000


def walk_repo(
    repo_dir: Path | str, max_files: int = DEFAULT_MAX_FILES
) -> Iterator[Tuple[str, int]]:
    """Yield ``(relative_path, size_bytes)`` for each file in ``repo_dir``.

    Symlinks are not followed. Paths use forward slashes regardless of OS.
    """
    base = Path(repo_dir)
    yielded = 0
    for dirpath, dirnames, filenames in os.walk(base, followlinks=False):
        dirnames[:] = [d for d in dirnames if d not in IGNORE_DIRS]
        for fname in filenames:
            full = Path(dirpath) / fname
            try:
                size = full.stat().st_size
            except OSError:
                continue
            rel = str(full.relative_to(base)).replace(os.sep, "/")
            yield rel, size
            yielded += 1
            if yielded >= max_files:
                return
