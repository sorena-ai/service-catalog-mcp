"""Helm chart extractions.

For every ``Chart.yaml`` under the repo, emit a ``helm_chart`` row with
the chart's name, version, app version, type, kubeVersion, and the list
of dependency chart names (full dep rows go to ``repository_dependencies``
via the deterministic dependency scanner).
"""

from __future__ import annotations

from pathlib import Path
from typing import List

from sdk.indexer.db.extractions import RepositoryExtraction
from ._yaml import safe_load_one


def scan_helm(
    files: list[tuple[str, int]], repo_dir: Path | str, user_id: str, repository_name: str
) -> List[RepositoryExtraction]:
    base = Path(repo_dir)
    rows: List[RepositoryExtraction] = []
    for rel, _ in files:
        if rel.rsplit("/", 1)[-1] == "Chart.yaml":
            path = base / rel
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
                        "chart_file": rel,
                    },
                    workspace_path=rel.rsplit("/", 1)[0] if "/" in rel else ".",
                    evidence=[{"kind": "manifest", "path": rel}],
                )
            )
    return rows


__all__ = ["scan_helm"]
