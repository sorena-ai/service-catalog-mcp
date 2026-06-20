"""Workspace analyzer — codebase-wide LLM pass + structural scanners.

The codebase pass (``run_workspace_analysis``) runs the agent CLI against the
whole cloned workspace and persists ``CodebaseContext`` rows. Structural
scanners (tree, languages, workspaces) live under ``scanners/``. Task ordering
is owned by the event-level coordinator in ``indexer/orchestrator.py``.
"""

from .analysis import run_workspace_analysis
from .assembler import (
    ExistingRepoCard,
    NewRepoEntry,
    assemble_input,
    load_existing_repo_cards,
)
from .parser import WorkspaceParseError, parse_output

__all__ = [
    "run_workspace_analysis",
    "ExistingRepoCard",
    "NewRepoEntry",
    "assemble_input",
    "load_existing_repo_cards",
    "WorkspaceParseError",
    "parse_output",
]
