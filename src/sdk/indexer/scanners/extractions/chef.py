"""Chef cookbook extractions.

For every ``metadata.rb`` under the repo, parse the cookbook DSL for
``name``, ``version``, ``maintainer``, ``description``, ``license``, and
``supports`` (platforms). Cookbook deps from ``depends`` lines are written
to ``repository_dependencies`` by the deterministic dependency scanner.

The metadata.rb format is Ruby — we extract only the obvious top-level
``directive 'value'`` pattern. Anything more elaborate is rejected
gracefully.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import List

from ...db.extractions import RepositoryExtraction
from .._walker import IGNORE_DIRS

logger = logging.getLogger(__name__)

DIRECTIVE_LINE = re.compile(
    r"""^\s*(?P<key>name|version|maintainer|maintainer_email|description|license|long_description|chef_version|issues_url|source_url)\s+["'](?P<value>[^"']+)["']\s*$"""
)
SUPPORTS_LINE = re.compile(
    r"""^\s*supports\s+["'](?P<platform>[^"']+)["']\s*(?:,\s*["'](?P<version>[^"']+)["'])?"""
)


def scan_chef(
    repo_dir: Path | str, user_id: str, repository_name: str
) -> List[RepositoryExtraction]:
    base = Path(repo_dir)
    rows: List[RepositoryExtraction] = []
    for path in base.rglob("metadata.rb"):
        rel = path.relative_to(base)
        if any(part in IGNORE_DIRS for part in rel.parts):
            continue
        rel_str = str(rel).replace("\\", "/")
        parsed = _parse_metadata(path)
        if not parsed.get("name"):
            continue
        parsed["metadata_file"] = rel_str
        rows.append(
            RepositoryExtraction(
                user_id=user_id,
                repository_name=repository_name,
                extraction_type="chef_cookbook",
                data=parsed,
                workspace_path=str(rel.parent).replace("\\", "/") if rel.parent != Path() else ".",
                evidence=[{"kind": "manifest", "path": rel_str}],
            )
        )
    return rows


def _parse_metadata(path: Path) -> dict:
    out: dict = {"supports": []}
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith("#"):
                    continue
                m = DIRECTIVE_LINE.match(line)
                if m:
                    out[m.group("key")] = m.group("value")
                    continue
                m = SUPPORTS_LINE.match(line)
                if m:
                    out["supports"].append(
                        {"platform": m.group("platform"), "version": m.group("version")}
                    )
    except Exception as exc:
        logger.warning("Failed to parse %s: %s", path, exc)
    return out


__all__ = ["scan_chef"]
