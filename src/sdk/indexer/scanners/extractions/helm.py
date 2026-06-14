"""Helm chart extractions.

For every ``Chart.yaml`` under the repo, emit a ``helm_chart`` row with
the chart's name, version, app version, type, kubeVersion, and the list
of dependency chart names (full dep rows go to ``repository_dependencies``
via the deterministic dependency scanner).
"""

from __future__ import annotations

from pathlib import Path
from typing import List

from ...db.extractions import RepositoryExtraction
from .._walker import IGNORE_DIRS
from ._yaml import safe_load_one


def scan_helm(
    repo_dir: Path | str, user_id: str, repository_name: str
) -> List[RepositoryExtraction]:
    base = Path(repo_dir)
    rows: List[RepositoryExtraction] = []
    for path in base.rglob("Chart.yaml"):
        rel = path.relative_to(base)
        if any(part in IGNORE_DIRS for part in rel.parts):
            continue
        rel_str = str(rel).replace("\\", "/")
        data = safe_load_one(path)
        if not isinstance(data, dict):
            continue
        deps = data.get("dependencies") or []
        rows.append(
            RepositoryExtraction(
                user_id=user_id,
                repository_name=repository_name,
                extraction_type="helm_chart",
                data={
                    "name": data.get("name"),
                    "version": data.get("version"),
                    "app_version": data.get("appVersion"),
                    "type": data.get("type"),
                    "kube_version": data.get("kubeVersion"),
                    "api_version": data.get("apiVersion"),
                    "dependency_names": [
                        d.get("name") for d in deps if isinstance(d, dict) and d.get("name")
                    ],
                    "chart_file": rel_str,
                },
                workspace_path=str(rel.parent).replace("\\", "/") if rel.parent != Path() else ".",
                evidence=[{"kind": "manifest", "path": rel_str}],
            )
        )
    return rows


__all__ = ["scan_helm"]
