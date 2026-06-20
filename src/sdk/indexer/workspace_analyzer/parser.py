"""Codebase-pass output parser.

Reads ``__codebase_output.json`` produced by Claude and converts each
top-level key into a ``CodebaseContext`` row. Validates that all required
keys from ``CODEBASE_CONTEXT_TYPES`` are present. Missing keys raise so
the caller can fail the run (instead of silently writing an incomplete
codebase view).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import List

from sdk.indexer.db.codebase_contexts import CodebaseContext
from sdk import vocabulary as vocab_mod

logger = logging.getLogger(__name__)


class WorkspaceParseError(RuntimeError):
    pass


def parse_output(output_path: Path, user_id: str) -> List[CodebaseContext]:
    if not output_path.exists():
        raise WorkspaceParseError(f"Codebase pass output missing: {output_path}")

    try:
        raw = output_path.read_text(encoding="utf-8")
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise WorkspaceParseError(f"Invalid JSON in {output_path}: {exc}") from exc

    if not isinstance(data, dict):
        raise WorkspaceParseError(f"Codebase pass output must be a JSON object, got {type(data).__name__}")

    required = set(vocab_mod.CODEBASE_CONTEXT_TYPES)
    missing = required - set(data.keys())
    if missing:
        raise WorkspaceParseError(f"Codebase pass output missing keys: {sorted(missing)}")

    rows: List[CodebaseContext] = []
    for ctype in vocab_mod.CODEBASE_CONTEXT_TYPES:
        section = data[ctype]
        if not isinstance(section, dict):
            raise WorkspaceParseError(
                f"Codebase pass key {ctype} must be an object, got {type(section).__name__}"
            )
        content = section.get("content")
        if not isinstance(content, str) or not content.strip():
            raise WorkspaceParseError(f"Codebase pass key {ctype}.content must be a non-empty string")
        rows.append(
            CodebaseContext(
                user_id=user_id,
                context_type=ctype,
                content=content.strip(),
                referenced_repositories=_string_list(section.get("referenced_repositories")),
                tags=_string_list(section.get("tags")),
            )
        )
    return rows


def _string_list(value) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(x) for x in value if isinstance(x, (str, int))]
