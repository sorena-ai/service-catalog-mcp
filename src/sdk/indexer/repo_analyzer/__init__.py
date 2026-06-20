"""Repo analyzer — per-repo LLM pass + detail scanners.

``run_repo_analysis`` generates per-repo ``RepositoryContext`` rows from the
deterministic facts produced by the detail scanners (files, dependencies,
extractions) under ``scanners/``. Task ordering is owned by the event-level
coordinator in ``indexer/orchestrator.py``.
"""

from .analysis import RepoParseError, run_repo_analysis

__all__ = [
    "run_repo_analysis",
    "RepoParseError",
]
