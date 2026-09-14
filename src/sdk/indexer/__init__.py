"""Indexer package.

Owns:
  - DB models for per-dimension and generic collections (``db/``)
  - Workspace analyzer (``workspace_analyzer/``): codebase-wide LLM pass +
    structural scanners (tree, languages, workspaces)
  - Repo analyzer (``repo_analyzer/``): per-repo LLM pass + detail scanners
    (files, dependencies, extractions)
  - Shared scan helpers (``_walker.py``, ``lang_extensions.py``)
  - Edge builder (``relationships.py``)
  - Event-level coordinator that sequences both analyzers (``orchestrator.py``)
  - Per-user scheduler (``scheduler.py``)
"""

from .orchestrator import run_indexing_event
from .scheduler import IndexingScheduler

__all__ = [
    "IndexingScheduler",
    "run_indexing_event",
]
