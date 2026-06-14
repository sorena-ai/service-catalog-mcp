"""Codebase pass — runs Claude CLI against the cloned workspace
and persists ``CodebaseContext`` rows.

The orchestrator calls ``run_tier1`` after preparing the clone
workspace and before per-repo repository passes.
"""

from .assembler import (
    ExistingRepoCard,
    NewRepoEntry,
    assemble_input,
    load_existing_repo_cards,
)
from .orchestrator import run_tier1
from .parser import Tier1ParseError, parse_output

__all__ = [
    "ExistingRepoCard",
    "NewRepoEntry",
    "Tier1ParseError",
    "assemble_input",
    "load_existing_repo_cards",
    "parse_output",
    "run_tier1",
]
