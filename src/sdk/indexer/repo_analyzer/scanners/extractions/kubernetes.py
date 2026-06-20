"""Kubernetes extractions.

Walks YAML files under the repo and emits a ``kubernetes_object`` row for
every doc that has ``apiVersion`` and ``kind`` set. Multi-document YAML
files are unpacked.

Skips compose files (handled by docker scanner) and helm chart values
(scanned separately).
"""

from __future__ import annotations

from pathlib import Path
from typing import List

from sdk.indexer.db.extractions import RepositoryExtraction
from ._yaml import safe_load_all

SKIP_BASENAMES = {
    "docker-compose.yml",
    "docker-compose.yaml",
    "compose.yml",
    "compose.yaml",
    "Chart.yaml",
    "values.yaml",
    "values.yml",
}


def scan_kubernetes(
    files: list[tuple[str, int]], repo_dir: Path | str, user_id: str, repository_name: str
) -> List[RepositoryExtraction]:
    base = Path(repo_dir)
    rows: List[RepositoryExtraction] = []
    for rel, _ in files:
        name = rel.rsplit("/", 1)[-1]
        if name in SKIP_BASENAMES:
            continue
        if not (name.endswith(".yaml") or name.endswith(".yml")):
            continue
        
        path = base / rel
        for doc in safe_load_all(path):
            if not isinstance(doc, dict):
                continue
            kind = doc.get("kind")
            api_version = doc.get("apiVersion")
            if not kind or not api_version:
                continue
            metadata = doc.get("metadata") or {}
            spec = doc.get("spec") or {}
            rows.append(
                RepositoryExtraction(
                    user_id=user_id,
                    repository_name=repository_name,
                    extraction_type="kubernetes_object",
                    data={
                        "api_version": api_version,
                        "kind": kind,
                        "name": metadata.get("name") if isinstance(metadata, dict) else None,
                        "namespace": metadata.get("namespace") if isinstance(metadata, dict) else None,
                        "labels": metadata.get("labels") if isinstance(metadata, dict) else None,
                        "replicas": spec.get("replicas") if isinstance(spec, dict) else None,
                        "manifest_file": rel,
                    },
                    evidence=[{"kind": "manifest", "path": rel}],
                )
            )
    return rows


__all__ = ["scan_kubernetes"]
