"""Terraform extractions.

For every ``*.tf`` file under the repo, emit a ``terraform_module`` row
per ``module "<name>" { ... }`` block plus a row per ``resource "<type>"``
declaration so cross-repo queries like "which repos provision an
``aws_s3_bucket``" work.

The HCL parser is intentionally lo-fi: regex over file contents. For
deeper analysis the orchestrator can shell out to ``hcl2-py`` later.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import List

from sdk.indexer.db.extractions import RepositoryExtraction

logger = logging.getLogger(__name__)

MODULE_BLOCK = re.compile(
    r"""module\s+"(?P<name>[^"]+)"\s*\{(?P<body>[^{}]*?)\}""",
    re.DOTALL,
)
SOURCE_LINE = re.compile(r"""source\s*=\s*"(?P<source>[^"]+)"\s*""")
VERSION_LINE = re.compile(r"""version\s*=\s*"(?P<version>[^"]+)"\s*""")
RESOURCE_BLOCK = re.compile(
    r"""resource\s+"(?P<type>[^"]+)"\s+"(?P<name>[^"]+)"\s*\{""",
)


def scan_terraform(
    files: list[tuple[str, int]], repo_dir: Path | str, user_id: str, repository_name: str
) -> List[RepositoryExtraction]:
    base = Path(repo_dir)
    rows: List[RepositoryExtraction] = []
    for rel, _ in files:
        if rel.endswith(".tf"):
            path = base / rel
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except Exception as exc:
                logger.warning("Failed to read %s: %s", path, exc)
                continue

            for m in MODULE_BLOCK.finditer(text):
                body = m.group("body")
                source_m = SOURCE_LINE.search(body)
                version_m = VERSION_LINE.search(body)
                rows.append(
                    RepositoryExtraction(
                        user_id=user_id,
                        repository_name=repository_name,
                        extraction_type="terraform_module",
                        data={
                            "name": m.group("name"),
                            "source": source_m.group("source") if source_m else None,
                            "version": version_m.group("version") if version_m else None,
                            "manifest_file": rel,
                        },
                        evidence=[{"kind": "manifest", "path": rel}],
                    )
                )

            for m in RESOURCE_BLOCK.finditer(text):
                rows.append(
                    RepositoryExtraction(
                        user_id=user_id,
                        repository_name=repository_name,
                        extraction_type="terraform_resource",
                        data={
                            "resource_type": m.group("type"),
                            "name": m.group("name"),
                            "manifest_file": rel,
                        },
                        evidence=[{"kind": "manifest", "path": rel}],
                    )
                )
    return rows


__all__ = ["scan_terraform"]
