"""Tree scanner — full path listing for a single repo."""

from __future__ import annotations

import hashlib
from pathlib import Path

from sdk.indexer.db.tree import RepositoryTree


def scan_tree(files: list[tuple[str, int]], user_id: str, repository_name: str) -> RepositoryTree:
    paths = sorted(rel for rel, _ in files)
    fingerprint = _fingerprint(paths)
    return RepositoryTree(
        user_id=user_id,
        repository_name=repository_name,
        paths=paths,
        file_count=len(paths),
        fingerprint=fingerprint,
    )


def _fingerprint(paths: list[str]) -> str:
    h = hashlib.sha256()
    for p in paths:
        h.update(p.encode("utf-8"))
        h.update(b"\n")
    return h.hexdigest()
